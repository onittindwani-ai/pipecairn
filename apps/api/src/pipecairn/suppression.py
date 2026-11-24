"""Suppression: addresses and domains that must never be contacted again. Checked before every send."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from pipecairn.models import Suppression
from pipecairn.util import email_domain, normalize_email
from sendora_core.audit import record_audit
from sendora_core.events import record_event


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
