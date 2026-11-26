"""What a real (non demo) install needs to start: mailboxes, a sequence, the do not contact list and the list of existing customers.

The demo gets all of these from the seed file. A real install makes them here, through the app (Deliverability, Sequences and Leads pages) or these routes.
"""

from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pipecairn import intake, metrics, templating
from pipecairn.api.deps import db, get_ctx, owner, writer
from pipecairn.api.routes_data import SequenceIn, check_steps, seq_row
from pipecairn.context import Ctx
from pipecairn.models import Mailbox, Sequence, Step, Suppression
from pipecairn.suppression import DOMAIN_RE, suppress_everywhere
from pipecairn.util import is_e164, is_valid_email, normalize_email
from sendora_core.audit import record_audit

router = APIRouter(prefix="/api", tags=["setup"])
MAX_VALUES = 20_000


class MailboxIn(BaseModel):
    address: str = Field(max_length=254)
    daily_cap: int = Field(default=30, ge=1, le=2000)
    warmup_days: int = Field(default=0, ge=0, le=730)
    spf_ok: bool = False
    dkim_ok: bool = False
    dmarc_ok: bool = False


@router.post("/mailboxes", summary="Add a sending mailbox (owner only)")
def add_mailbox(body: MailboxIn, s: Session = Depends(db, scope="function"), ctx: Ctx = Depends(get_ctx), u: dict = Depends(owner)):
    address = normalize_email(body.address)
    if not is_valid_email(address):
        raise HTTPException(422, "That is not an email address.")
    if s.scalars(select(Mailbox).where(Mailbox.address == address)).first() is not None:
        raise HTTPException(409, "That mailbox is already added.")
    mb = Mailbox(address=address, provider="smtp_imap", daily_cap=body.daily_cap, warmup_days=body.warmup_days, spf_ok=body.spf_ok, dkim_ok=body.dkim_ok, dmarc_ok=body.dmarc_ok, sent_day="")
    s.add(mb)
    s.flush()
    record_audit(s, u["user"], "mailbox.created", f"mailbox:{mb.id}", {"daily_cap": mb.daily_cap})
    # Every mailbox signs in with the one SMTP_USER and SMTP_PASSWORD, so the address must be that account or one it may send as.
    return next(r for r in metrics.deliverability(s) if r["id"] == mb.id)


class NewSequenceIn(SequenceIn):
    pass


@router.post("/sequences", summary="Create a sequence (owner only). It becomes the active one when there is none yet")
def create_sequence(body: NewSequenceIn, s: Session = Depends(db, scope="function"), u: dict = Depends(owner)):
    check_steps(body.steps)
    has_active = s.scalars(select(Sequence).where(Sequence.active.is_(True))).first() is not None
    q = Sequence(name=body.name, active=not has_active)
    for i, st in enumerate(body.steps):
        q.steps.append(Step(position=i, channel=st.channel, delay_hours=st.delay_hours, subject=st.subject, body=st.body))
    s.add(q)
    s.flush()
    record_audit(s, u["user"], "sequence.created", f"sequence:{q.id}", {"steps": len(body.steps), "active": q.active})
    return seq_row(q)


@router.post("/sequences/{seq_id}/activate", summary="Make this the one sequence new leads are enrolled in (owner only)")
def activate_sequence(seq_id: int, s: Session = Depends(db, scope="function"), u: dict = Depends(owner)):
    q = s.get(Sequence, seq_id)
    if q is None:
        raise HTTPException(404, "That sequence does not exist.")
    for other in s.scalars(select(Sequence)):
        other.active = other.id == q.id
    record_audit(s, u["user"], "sequence.activated", f"sequence:{q.id}", {})
    return seq_row(q)


class ValuesIn(BaseModel):
    values: list[str] = Field(default_factory=list, max_length=MAX_VALUES)
    csv: str = Field(default="", max_length=2_000_000)


def _values(body: ValuesIn, columns: tuple[str, ...]) -> list[tuple[str, str]]:
    """(kind, value) pairs from a list, or from CSV text whose columns are among `columns` (a header row names them; with no header the first column is used)."""
    out: list[tuple[str, str]] = [("", v.strip()) for v in body.values if v.strip()]
    if body.csv.strip():
        rows = list(csv.reader(io.StringIO(body.csv)))
        head = [h.strip().lower() for h in rows[0]] if rows else []
        named = any(h in columns or h == "kind" for h in head)
        data = rows[1:] if named else rows
        idx = {h: i for i, h in enumerate(head)} if named else {}
        for r in data:
            if not r:
                continue
            col = next((c for c in columns if c in idx and idx[c] < len(r) and r[idx[c]].strip()), None)
            value = r[idx[col]].strip() if col else (r[0].strip() if not named else "")
            kind = r[idx["kind"]].strip().lower() if "kind" in idx and idx["kind"] < len(r) else (col or "")
            if value:
                out.append((kind, value))
    return out


def _kind(value: str, hint: str) -> str | None:
    if hint in {"email", "domain", "phone"}:
        return hint
    if "@" in value:
        return "email"
    if is_e164(value):
        return "phone"
    return "domain" if "." in value else None


@router.post("/suppressions", summary="Never contact these addresses, domains or phone numbers (the old unsubscribe list)")
def add_suppressions(body: ValuesIn, s: Session = Depends(db, scope="function"), u: dict = Depends(writer)):
    """Takes a list (`values`) or CSV text (`csv`, a column named email, domain, phone or value, optionally `kind`). Leads already imported from them stop at once."""
    added = stopped = skipped = 0
    for hint, value in _values(body, ("email", "domain", "phone", "value")):
        kind = _kind(value, hint)
        if kind is None or (kind == "email" and not is_valid_email(value)) or (kind == "domain" and not DOMAIN_RE.match(normalize_email(value))):
            skipped += 1
            continue
        before = s.scalar(select(func.count()).select_from(Suppression)) or 0
        stopped += suppress_everywhere(s, kind, value, "imported do not contact list", "import", actor=u["user"])
        added += (s.scalar(select(func.count()).select_from(Suppression)) or 0) - before
    record_audit(s, u["user"], "suppressions.imported", None, {"added": added, "leads_stopped": stopped, "skipped": skipped})
    return {"added": added, "leads_stopped": stopped, "skipped": skipped}


@router.get("/suppressions", summary="How many do not contact entries there are, and the newest ones")
def list_suppressions(s: Session = Depends(db, scope="function")):
    rows = list(s.scalars(select(Suppression).order_by(Suppression.id.desc()).limit(200)))
    total = int(s.scalar(select(func.count()).select_from(Suppression)) or 0)
    return {"total": total, "rows": [{"kind": r.kind, "value": r.value, "reason": r.reason, "source": r.source} for r in rows]}


@router.post("/customers", summary="Mark existing customers so they are never prospected (domains or email addresses)")
def add_customers(body: ValuesIn, s: Session = Depends(db, scope="function"), u: dict = Depends(writer)):
    """Takes a list (`values`) or CSV text (`csv`, a column named domain or email). A lead already imported from a customer company stops at once."""
    values = [v for _, v in _values(body, ("domain", "email", "value"))]
    if not values:
        raise HTTPException(422, "Send at least one domain or email address.")
    rep = intake.mark_customers(s, values)
    record_audit(s, u["user"], "customers.imported", None, rep)
    return rep
