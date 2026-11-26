"""Intake: import, dedupe, flag, enrich, score and enroll. Nothing here sends anything."""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from pipecairn import scoring
from pipecairn.models import Activity, Company, Contact, Deal, Enrollment, Lead, Sequence
from pipecairn.suppression import suppression_reason
from pipecairn.util import clean_person_text, email_domain, is_e164, is_role_based, is_valid_email, normalize_email, zone
from sendora_core.events import record_event
from sendora_core.llm import LLM

CSV_COLUMNS = ("first_name", "last_name", "email", "phone", "title", "company", "domain", "timezone", "source", "sms_consent", "industry", "size", "country", "is_customer")
MAX_CSV_BYTES = 2_000_000
YES = {"1", "true", "yes", "y"}


@dataclass
class ImportReport:
    rows: int = 0
    created: int = 0
    duplicates: int = 0
    flagged: dict[str, int] = field(default_factory=dict)

    def flag(self, name: str) -> None:
        self.flagged[name] = self.flagged.get(name, 0) + 1


HEADER_ALIASES = {
    "e_mail": "email", "email_address": "email", "mail": "email", "firstname": "first_name", "first": "first_name", "given_name": "first_name", "lastname": "last_name",
    "last": "last_name", "surname": "last_name", "family_name": "last_name", "phone_number": "phone", "mobile": "phone", "telephone": "phone", "job_title": "title",
    "position": "title", "company_name": "company", "organisation": "company", "organization": "company", "website": "domain", "time_zone": "timezone", "tz": "timezone",
    "sms_opt_in": "sms_consent", "customer": "is_customer", "employees": "size", "company_size": "size",
}
# The width of the column each field is stored in. A cell longer than this is not cut and not stored: the row is skipped and counted, so a database that enforces
# the width (Postgres) never turns one bad cell into an error for the whole file.
FIELD_LIMITS = {"first_name": 80, "last_name": 80, "email": 254, "phone": 32, "title": 120, "company": 200, "domain": 200, "timezone": 64, "source": 40, "industry": 80}


def normalise_header(name: str) -> str:
    """"First Name", " E-mail ", "first-name" and "FIRST_NAME" are all first_name or email: case, spaces, hyphens and a byte order mark do not matter."""
    key = re.sub(r"[\s\-.]+", "_", (name or "").replace("\ufeff", "").strip().lower()).strip("_")
    return HEADER_ALIASES.get(key, key)


def parse_csv_report(text: str) -> tuple[list[dict[str, str]], list[str]]:
    """(rows, the headers that were not recognised and so were ignored). Raises ValueError with a plain message for a file that cannot be read."""
    if len(text.encode()) > MAX_CSV_BYTES:
        raise ValueError("The CSV is larger than 2 MB. Split it into smaller files.")
    try:
        reader = csv.DictReader(io.StringIO(text.replace("\x00", "")))
        names = list(reader.fieldnames or [])
        mapping = {raw: normalise_header(raw) for raw in names}
        if "email" not in mapping.values():
            raise ValueError("The CSV needs at least an email column. Columns found: " + (", ".join(n.strip() for n in names if n and n.strip()) or "none"))
        ignored = [raw.strip() for raw, norm in mapping.items() if norm not in CSV_COLUMNS and raw and raw.strip()]
        rows = [{mapping[k]: (v or "").strip() for k, v in row.items() if k in mapping and mapping[k] in CSV_COLUMNS and isinstance(v, str | None)} for row in reader]
    except csv.Error as exc:  # for example "field larger than field limit", or a stray quote that runs to the end of the file
        raise ValueError(f"The CSV could not be read ({exc}). Check for a cell that is far too long or a quote mark that is never closed.") from exc
    return rows, ignored


def parse_csv(text: str) -> list[dict[str, str]]:
    return parse_csv_report(text)[0]


def _int(value: Any) -> int:
    try:
        return max(0, int(str(value).strip() or 0))
    except ValueError:
        return 0


def _truthy(value: Any) -> bool:
    return value is True or str(value).strip().lower() in YES


def _company(session: Session, name: str, domain: str, row: dict[str, Any]) -> Company | None:
    domain = (domain or "").strip().lower()
    if not domain:
        return None
    c = session.scalars(select(Company).where(Company.domain == domain)).first()
    if c is None:
        c = Company(name=name or domain, domain=domain, industry=str(row.get("industry", "")).strip().lower()[:80], size=_int(row.get("size", 0)),
                    country=(str(row.get("country", "")).strip().upper() or "US")[:2], is_customer=_truthy(row.get("is_customer", False)))
        session.add(c)
        session.flush()
    else:
        # A company we already know can still learn what a later file says: its industry and size when they were empty, and that it is a customer.
        if not c.industry and row.get("industry"):
            c.industry = str(row["industry"]).strip().lower()[:80]
        if not c.size and row.get("size"):
            c.size = _int(row["size"])
        if _truthy(row.get("is_customer", False)) and not c.is_customer:
            mark_customer(session, c)
    return c


def mark_customer(session: Session, company: Company) -> int:
    """This company is already a customer, so it is never prospected. Leads already imported from it stop now. Returns how many leads changed."""
    company.is_customer = True
    n = 0
    for lead in session.scalars(select(Lead).join(Contact, Lead.contact_id == Contact.id).where(Contact.company_id == company.id)):
        if lead.status in {"won", "lost", "suppressed", "dead"}:
            continue
        lead.flags = sorted(set(lead.flags or []) | {"existing_customer"})
        lead.status = "dead"
        for e in session.scalars(select(Enrollment).where(Enrollment.lead_id == lead.id, Enrollment.status.in_(("active", "paused")))):
            e.status, e.stop_reason, e.next_send_at = "stopped", "existing_customer", None
        n += 1
    session.flush()
    return n


def mark_customers(session: Session, domains: list[str]) -> dict[str, int]:
    """Mark every company on a list of domains (or email addresses) as a customer. A domain we have never seen is stored, so a later import is blocked too."""
    found = changed = 0
    for raw in domains:
        d = email_domain(raw) if "@" in raw else raw.strip().lower()
        if not d or "." not in d:
            continue
        c = session.scalars(select(Company).where(Company.domain == d)).first()
        if c is None:
            c = Company(name=d, domain=d, is_customer=False)
            session.add(c)
            session.flush()
        else:
            found += 1
        changed += mark_customer(session, c)
    session.flush()
    return {"domains": len(domains), "already_known": found, "leads_stopped": changed}


def import_leads(session: Session, rows: list[dict[str, Any]], now: datetime, default_source: str = "csv_list", default_timezone: str = "") -> ImportReport:
    rep = ImportReport(rows=len(rows))
    fallback_zone = default_timezone if zone(default_timezone) else ""
    for row in rows:
        if any(len(str(row.get(f, ""))) > limit for f, limit in FIELD_LIMITS.items()):
            rep.flag("cell_too_long")  # skipped, not cut: a name or an address that long is a broken file, and the row would not fit its column
            continue
        email = normalize_email(str(row.get("email", "")))
        if not email:
            rep.flag("missing_email")
            continue
        # names and titles go into the first email, so a file gets the same cleaning as the web form: no links, markup, template fields or line breaks
        row = {**row, **{f: clean_person_text(str(row[f]), FIELD_LIMITS[f]) for f in ("first_name", "last_name", "title") if f in row}}
        existing = session.scalars(select(Contact).where(Contact.email == email)).first()
        if existing is not None:
            rep.duplicates += 1
            for f in ("first_name", "last_name", "phone", "title", "timezone"):
                if not getattr(existing, f) and row.get(f):
                    setattr(existing, f, str(row[f]))
            if _truthy(row.get("is_customer", False)) and existing.company is not None and not existing.company.is_customer:
                mark_customer(session, existing.company)  # a later file says this person's company is a customer
            continue
        company = _company(session, str(row.get("company", "")), str(row.get("domain", "")) or email_domain(email), row)
        flags: list[str] = []
        if not is_valid_email(email):
            flags.append("invalid_email")
        if is_role_based(email):
            flags.append("role_based")
        tz = str(row.get("timezone", ""))
        if not zone(tz) and fallback_zone:
            tz = fallback_zone  # DEFAULT_TIMEZONE: the owner chose this for rows that came with no valid zone
        if not zone(tz):
            flags.append("invalid_timezone")
        consent = str(row.get("sms_consent", "")).lower() in YES
        phone = str(row.get("phone", "")).strip()
        if consent and not is_e164(phone):
            flags.append("invalid_phone")
        contact = Contact(company_id=company.id if company else None, first_name=str(row.get("first_name", "")), last_name=str(row.get("last_name", "")), email=email,
                          phone=phone, title=str(row.get("title", "")), timezone=tz, sms_consent=consent, created_at=now)
        session.add(contact)
        session.flush()
        status = "new"
        if company is not None and company.is_customer:
            flags.append("existing_customer")
        if suppression_reason(session, email=email):
            status = "suppressed"
        elif {"invalid_email", "role_based", "existing_customer"} & set(flags):
            status = "dead"
        lead = Lead(contact_id=contact.id, source=str(row.get("source") or default_source), status=status, flags=flags, created_at=now)
        session.add(lead)
        session.flush()
        for f in flags:
            rep.flag(f)
        if status == "suppressed":
            rep.flag("suppressed")
        rep.created += 1
        session.add(Activity(lead_id=lead.id, kind="intake", summary=f"Imported from {lead.source}" + (f" with flags: {', '.join(flags)}" if flags else ""), created_at=now))
    record_event(session, "leads.imported", None, None, {"rows": rep.rows, "created": rep.created, "duplicates": rep.duplicates})
    session.flush()
    return rep


def enrich_pending(session: Session, directory: dict[str, dict]) -> int:
    """Fill a company's industry and size from a local directory when missing. No outside lookup is made."""
    n = 0
    for lead in session.scalars(select(Lead).where(Lead.status == "new")):
        c = lead.contact.company
        if c is not None and (not c.industry or not c.size):
            known = directory.get(c.domain)
            if known:
                c.industry, c.size = c.industry or known.get("industry", ""), c.size or int(known.get("size", 0))
            else:
                lead.flags = sorted(set(lead.flags or []) | {"enrichment_missing"})
        lead.status = "enriched"
        n += 1
    session.flush()
    return n


def deal_value_cents(size: int, values: tuple[int, int, int] = (150_000, 600_000, 1_200_000)) -> int:
    """A placeholder estimate by company size, used only to size the pipeline. Set DEAL_VALUE_SMALL_CENTS, DEAL_VALUE_MEDIUM_CENTS and DEAL_VALUE_LARGE_CENTS to your own price list."""
    return values[0] if size <= 10 else values[1] if size <= 200 else values[2]


def score_pending(session: Session, llm: LLM | None, targets: tuple[str, ...] = scoring.TARGET_INDUSTRIES, deal_values: tuple[int, int, int] = (150_000, 600_000, 1_200_000)) -> int:
    n = 0
    for lead in session.scalars(select(Lead).where(Lead.status.in_(("new", "enriched")))):
        c = lead.contact
        f = scoring.Features(title=c.title, company_size=c.company.size if c.company else 0, industry=c.company.industry if c.company else "", email=c.email, source=lead.source)
        res = scoring.score_lead(f, targets)
        lead.score, lead.score_breakdown = res.score, res.breakdown
        lead.score_explanation = scoring.explain_score(llm, f, res) if llm else ""
        if lead.status in {"new", "enriched"}:
            lead.status = "scored"
        if session.scalars(select(Deal).where(Deal.lead_id == lead.id)).first() is None:
            session.add(Deal(lead_id=lead.id, stage="new", value_cents=deal_value_cents(f.company_size, deal_values)))
        n += 1
    session.flush()
    return n


BLOCKING_FLAGS = {"invalid_email", "role_based", "existing_customer", "invalid_timezone"}


def enroll_pending(session: Session, sequence: Sequence, now: datetime, min_score: int = 40) -> int:
    n = 0
    for lead in session.scalars(select(Lead).where(Lead.status == "scored", Lead.score >= min_score)):
        if BLOCKING_FLAGS & set(lead.flags or []):
            continue
        if session.scalars(select(Enrollment).where(Enrollment.lead_id == lead.id, Enrollment.sequence_id == sequence.id)).first():
            continue
        session.add(Enrollment(lead_id=lead.id, sequence_id=sequence.id, current_step=0, status="active", next_send_at=now, created_at=now))
        lead.status = "enrolled"
        n += 1
    session.flush()
    return n
