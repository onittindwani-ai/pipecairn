"""Intake: import, dedupe, flag, enrich, score and enroll. Nothing here sends anything."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from pipecairn import scoring
from pipecairn.models import Activity, Company, Contact, Deal, Enrollment, Lead, Sequence
from pipecairn.suppression import suppression_reason
from pipecairn.util import email_domain, is_e164, is_role_based, is_valid_email, normalize_email, zone
from sendora_core.events import record_event
from sendora_core.llm import LLM

CSV_COLUMNS = ("first_name", "last_name", "email", "phone", "title", "company", "domain", "timezone", "source", "sms_consent")
MAX_CSV_BYTES = 2_000_000


@dataclass
class ImportReport:
    rows: int = 0
    created: int = 0
    duplicates: int = 0
    flagged: dict[str, int] = field(default_factory=dict)

    def flag(self, name: str) -> None:
        self.flagged[name] = self.flagged.get(name, 0) + 1


def parse_csv(text: str) -> list[dict[str, str]]:
    if len(text.encode()) > MAX_CSV_BYTES:
        raise ValueError("The CSV is larger than 2 MB. Split it into smaller files.")
    reader = csv.DictReader(io.StringIO(text))
    missing = {"email"} - set(reader.fieldnames or [])
    if missing:
        raise ValueError("The CSV needs at least an email column. Columns found: " + ", ".join(reader.fieldnames or ["none"]))
    return [{k: (v or "").strip() for k, v in row.items() if k in CSV_COLUMNS} for row in reader]


def _company(session: Session, name: str, domain: str, row: dict[str, Any]) -> Company | None:
    domain = (domain or "").strip().lower()
    if not domain:
        return None
    c = session.scalars(select(Company).where(Company.domain == domain)).first()
    if c is None:
        c = Company(name=name or domain, domain=domain, industry=str(row.get("industry", "")), size=int(row.get("size", 0) or 0),
                    country=str(row.get("country", "US")), is_customer=bool(row.get("is_customer", False)))
        session.add(c)
        session.flush()
    return c


def import_leads(session: Session, rows: list[dict[str, Any]], now: datetime, default_source: str = "csv_list") -> ImportReport:
    rep = ImportReport(rows=len(rows))
    for row in rows:
        email = normalize_email(str(row.get("email", "")))
        if not email:
            rep.flag("missing_email")
            continue
        existing = session.scalars(select(Contact).where(Contact.email == email)).first()
        if existing is not None:
            rep.duplicates += 1
            for f in ("first_name", "last_name", "phone", "title", "timezone"):
                if not getattr(existing, f) and row.get(f):
                    setattr(existing, f, str(row[f]))
            continue
        company = _company(session, str(row.get("company", "")), str(row.get("domain", "")) or email_domain(email), row)
        flags: list[str] = []
        if not is_valid_email(email):
            flags.append("invalid_email")
        if is_role_based(email):
            flags.append("role_based")
        if not zone(str(row.get("timezone", ""))):
            flags.append("invalid_timezone")
        consent = str(row.get("sms_consent", "")).lower() in {"1", "true", "yes", "y"}
        phone = str(row.get("phone", "")).strip()
        if consent and not is_e164(phone):
            flags.append("invalid_phone")
        contact = Contact(company_id=company.id if company else None, first_name=str(row.get("first_name", "")), last_name=str(row.get("last_name", "")), email=email,
                          phone=phone, title=str(row.get("title", "")), timezone=str(row.get("timezone", "")), sms_consent=consent, created_at=now)
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


def deal_value_cents(size: int) -> int:
    """A placeholder estimate by company size, used only to size the pipeline. Replace it with your own price list."""
    return 150_000 if size <= 10 else 600_000 if size <= 200 else 1_200_000


def score_pending(session: Session, llm: LLM | None, targets: tuple[str, ...] = scoring.TARGET_INDUSTRIES) -> int:
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
            session.add(Deal(lead_id=lead.id, stage="new", value_cents=deal_value_cents(f.company_size)))
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
