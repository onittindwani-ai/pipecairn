"""Suppression: addresses and domains that must never be contacted again. Checked before every send."""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from pipecairn.models import Suppression
from pipecairn.util import email_domain, normalize_email
from sendora_core.audit import record_audit
from sendora_core.events import record_event


DOMAIN_RE = re.compile(r"^[a-z0-9](?:[a-z0-9\-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9\-]*[a-z0-9])?)+$")


def add_suppression(session: Session, kind: str, value: str, reason: str, source: str, actor: str = "system") -> bool:
    """Returns True when a new row was added. Safe to call twice."""
    v = normalize_email(value) if kind in {"email", "domain"} else value.strip()
    if session.scalars(select(Suppression).where(Suppression.kind == kind, Suppression.value == v)).first():
        return False
    session.add(Suppression(kind=kind, value=v, reason=reason, source=source))
    session.flush()
    record_audit(session, actor, "suppression.added", f"{kind}:{v}", {"reason": reason, "source": source})
    record_event(session, "suppression.added", "suppression", v, {"kind": kind, "reason": reason})
    return True


def suppression_reason(session: Session, *, email: str = "", phone: str = "") -> str:
    """Empty string when the contact may be written to, otherwise the reason. Always reads the database, never a cache."""
    e = normalize_email(email)
    if e:
        if session.scalars(select(Suppression).where(Suppression.kind == "email", Suppression.value == e)).first():
            return "suppressed_email"
        d = email_domain(e)
        if d and session.scalars(select(Suppression).where(Suppression.kind == "domain", Suppression.value == d)).first():
            return "suppressed_domain"
    if phone and session.scalars(select(Suppression).where(Suppression.kind == "phone", Suppression.value == phone.strip())).first():
        return "suppressed_phone"
    return ""


def suppress_everywhere(session: Session, kind: str, value: str, reason: str, source: str, actor: str = "system") -> int:
    """Add a suppression AND stop every lead it covers right now, so nothing already imported or enrolled is written to in the meantime.
    kind is email, domain or phone. Returns how many leads were stopped. Safe to call twice."""
    from sqlalchemy import func

    from pipecairn.models import Contact, Enrollment, Lead

    v = normalize_email(value) if kind in {"email", "domain"} else value.strip()
    if kind == "domain" and not DOMAIN_RE.match(v):
        raise ValueError("That is not a domain name.")  # a value like _.com or %.com would otherwise match every address in the LIKE below
    add_suppression(session, kind, value, reason, source, actor=actor)
    where = {"email": func.lower(Contact.email) == v, "domain": func.lower(Contact.email).like(f"%@{v}"), "phone": Contact.phone == v}[kind]
    n = 0
    for lead in session.scalars(select(Lead).join(Contact, Lead.contact_id == Contact.id).where(where)):
        if lead.status in {"won", "suppressed"}:
            continue
        lead.status = "suppressed"
        for e in session.scalars(select(Enrollment).where(Enrollment.lead_id == lead.id, Enrollment.status.in_(("active", "paused")))):
            e.status, e.stop_reason, e.next_send_at, e.paused_until = "stopped", "suppressed", None, None
        n += 1
    session.flush()
    return n


def lift_suppression(session: Session, lead, actor: str, reason: str) -> dict:
    """Undo a stop for one lead (an owner decision, audited). The lead's own address and phone number are removed from the list. The lead goes to "replied", never back
    into a sequence on its own: a person writes to them. A stop that comes from the whole domain stays: it is not about this person. Raises ValueError when there is
    nothing to lift."""
    c = lead.contact
    email = normalize_email(c.email)
    domain = email_domain(email)
    rows = list(session.scalars(select(Suppression).where(Suppression.kind == "email", Suppression.value == email)))
    if c.phone:
        rows += list(session.scalars(select(Suppression).where(Suppression.kind == "phone", Suppression.value == c.phone.strip())))
    by_domain = bool(domain and session.scalars(select(Suppression).where(Suppression.kind == "domain", Suppression.value == domain)).first())
    if not rows and lead.status != "suppressed":
        raise ValueError("This person is not on the do not contact list.")
    if by_domain and not rows:
        raise ValueError("This person is stopped because their whole domain is on the do not contact list. Remove the domain, not the person.")
    for row in rows:
        session.delete(row)
    lead.status = "replied"
    session.flush()
    record_audit(session, actor, "suppression.lifted", f"lead:{lead.id}", {"reason": reason[:300], "removed": [r.kind for r in rows], "domain_still_stopped": by_domain})
    record_event(session, "suppression.lifted", "lead", lead.id, {"removed": len(rows)})
    return {"removed": len(rows), "domain_still_stopped": by_domain}
