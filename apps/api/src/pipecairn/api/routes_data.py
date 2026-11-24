from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from pipecairn import intake, metrics, templating
from pipecairn.api.deps import db, get_ctx, writer
from pipecairn.api.serializers import deal_row, iso, lead_row, message_row, reply_row
from pipecairn.context import Ctx
from pipecairn.inbox import approve_and_send, reject_reply
from pipecairn.jobs import active_sequence
from pipecairn.models import DEAL_STAGES, Activity, Company, Contact, Deal, Enrollment, Lead, Meeting, Message, Reply, Sequence, Step
from pipecairn.sender import STOP_STATUSES
from sendora_core.approvals import ApprovalError, pending
from sendora_core.audit import record_audit
from sendora_core.events import record_event
from sendora_core.safety import guard_write

router = APIRouter(prefix="/api", tags=["data"])


@router.get("/overview", summary="Numbers for the Overview page")
def overview(s: Session = Depends(db), ctx: Ctx = Depends(get_ctx)):
    now = ctx.now(s)
    out = metrics.overview(s, now)
    out["pending_approvals"] = len(pending(s))
    out["open_replies"] = int(s.scalar(select(func.count()).select_from(Reply).where(Reply.handled.is_(False))) or 0)
    out["scheduled"] = int(s.scalar(select(func.count()).select_from(Enrollment).where(Enrollment.status == "active", Enrollment.next_send_at.is_not(None))) or 0)
    out["now"] = iso(now)
    return out


@router.get("/leads", summary="List leads")
def leads(limit: int = Query(200, ge=1, le=5000), q: str = "", status: str = "", s: Session = Depends(db)):
    stmt = select(Lead).join(Contact).outerjoin(Company, Contact.company_id == Company.id).order_by(Lead.id.desc()).limit(limit)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(Contact.email).like(like), func.lower(Contact.first_name).like(like), func.lower(Contact.last_name).like(like), func.lower(Company.name).like(like)))
    wanted = [x.strip() for x in status.split(",") if x.strip()]  # one status, or several separated by commas
    if wanted:
        stmt = stmt.where(Lead.status.in_(wanted))
    rows = [lead_row(l) for l in s.scalars(stmt)]
    return {"count": len(rows), "total": int(s.scalar(select(func.count()).select_from(Lead)) or 0), "rows": rows}


@router.get("/leads/{lead_id}", summary="One lead with everything about it")
def lead_detail(lead_id: int, s: Session = Depends(db)):
    l = s.get(Lead, lead_id)
    if l is None:
        raise HTTPException(404, "That lead does not exist.")
    deal = s.scalars(select(Deal).where(Deal.lead_id == l.id)).first()
    acts = s.scalars(select(Activity).where(Activity.lead_id == l.id).order_by(Activity.id.desc()).limit(30))
    msgs = s.scalars(select(Message).where(Message.lead_id == l.id).order_by(Message.id.desc()).limit(30))
    return {**lead_row(l), "phone": l.contact.phone, "sms_consent": l.contact.sms_consent, "industry": l.contact.company.industry if l.contact.company else "",
            "company_size": l.contact.company.size if l.contact.company else 0, "score_breakdown": l.score_breakdown, "score_explanation": l.score_explanation,
            "deal": deal_row(deal) if deal else None, "activities": [{"kind": a.kind, "summary": a.summary, "at": iso(a.created_at)} for a in acts],
            "messages": [message_row(m) for m in msgs],
            "enrollments": [{"id": e.id, "status": e.status, "step": e.current_step, "next_send_at": iso(e.next_send_at), "stop_reason": e.stop_reason} for e in s.scalars(select(Enrollment).where(Enrollment.lead_id == l.id))]}


class ImportBody(BaseModel):
    csv: str = Field(max_length=2_000_000)


@router.post("/leads/import", summary="Import leads from CSV text")
def import_csv(body: ImportBody, s: Session = Depends(db), ctx: Ctx = Depends(get_ctx), u: dict = Depends(writer)):
    try:
        rows = intake.parse_csv(body.csv)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    rep = intake.import_leads(s, rows, ctx.now(s))
    record_audit(s, u["user"], "leads.imported", None, {"rows": rep.rows, "created": rep.created, "duplicates": rep.duplicates})
    return {"rows": rep.rows, "created": rep.created, "duplicates": rep.duplicates, "flagged": rep.flagged}


@router.post("/leads/process", summary="Enrich, score and enrol new leads now")
def process(s: Session = Depends(db), ctx: Ctx = Depends(get_ctx), u: dict = Depends(writer)):
    from pipecairn.jobs import job_enrich, job_score

    return {**job_enrich(s, ctx), **job_score(s, ctx)}


class SuppressIn(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=500)
    reason: str = Field(default="owner choice", max_length=200)


@router.post("/leads/suppress", summary="Never contact these leads again")
def suppress(body: SuppressIn, s: Session = Depends(db), u: dict = Depends(writer)):
    from pipecairn.suppression import add_suppression

    n = 0
    for lead in s.scalars(select(Lead).where(Lead.id.in_(body.ids))):
        add_suppression(s, "email", lead.contact.email, body.reason, "manual", actor=u["user"])
        lead.status = "suppressed"
        for e in s.scalars(select(Enrollment).where(Enrollment.lead_id == lead.id, Enrollment.status.in_(("active", "paused")))):
            e.status, e.stop_reason, e.next_send_at = "stopped", "manual_suppress", None
        n += 1
    return {"suppressed": n}


class StepIn(BaseModel):
    channel: str = Field(pattern="^(email|sms)$")
    delay_hours: int = Field(ge=0, le=24 * 60)
    subject: str = Field(default="", max_length=200)
    body: str = Field(max_length=5000)


class SequenceIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    steps: list[StepIn] = Field(min_length=1, max_length=10)


def seq_row(q: Sequence) -> dict:
    return {"id": q.id, "name": q.name, "active": q.active, "steps": [{"position": st.position, "channel": st.channel, "delay_hours": st.delay_hours, "subject": st.subject, "body": st.body} for st in q.steps],
            "variables": sorted(templating.KNOWN)}


@router.get("/sequences", summary="List sequences")
def sequences(s: Session = Depends(db)):
    return [seq_row(q) for q in s.scalars(select(Sequence).order_by(Sequence.id))]


@router.put("/sequences/{seq_id}", summary="Replace a sequence's steps")
def update_sequence(seq_id: int, body: SequenceIn, s: Session = Depends(db), u: dict = Depends(writer)):
    q = s.get(Sequence, seq_id)
    if q is None:
        raise HTTPException(404, "That sequence does not exist.")
    for i, st in enumerate(body.steps, 1):
        if not st.body.strip():
            raise HTTPException(422, f"Step {i} has no message. Write one before saving.")
        if i == 1 and st.channel == "email" and not st.subject.strip():
            raise HTTPException(422, "The first email needs a subject. Add one before saving. Follow ups may leave it empty to stay in the same thread.")
    for st in body.steps:
        bad = (templating.variables_in(st.subject) | templating.variables_in(st.body)) - templating.KNOWN
        if bad:
            raise HTTPException(422, f"Unknown field(s) {', '.join(sorted(bad))}. You can use: {', '.join(sorted(templating.KNOWN))}.")
    q.name = body.name
    q.steps.clear()
    s.flush()
    for i, st in enumerate(body.steps):
        q.steps.append(Step(position=i, channel=st.channel, delay_hours=st.delay_hours, subject=st.subject, body=st.body))
    s.flush()
    record_audit(s, u["user"], "sequence.updated", f"sequence:{q.id}", {"steps": len(body.steps)})
    return seq_row(q)


class PreviewIn(BaseModel):
    subject: str = ""
    body: str = ""
    lead_id: int | None = None


@router.post("/sequences/preview", summary="Show a step as one real lead would receive it")
def preview(body: PreviewIn, s: Session = Depends(db)):
    lead = s.get(Lead, body.lead_id) if body.lead_id else s.scalars(select(Lead).where(Lead.score.is_not(None)).order_by(Lead.id)).first()
    from pipecairn.sender import _ctx

    ctx_vars = _ctx(lead) if lead else {k: f"[{k}]" for k in templating.KNOWN}
    try:
        return {"subject": templating.render(body.subject, ctx_vars, header=True), "body": templating.render(body.body, ctx_vars), "lead": lead_row(lead)["name"] if lead else None, "error": None}
    except templating.TemplateError as exc:
        return {"subject": "", "body": "", "lead": None, "error": str(exc)}


@router.get("/inbox", summary="Replies, newest first")
def inbox(open: bool = False, s: Session = Depends(db)):
    stmt = select(Reply).order_by(Reply.id.desc()).limit(200)
    if open:
        stmt = stmt.where(Reply.handled.is_(False))
    out = []
    for r in s.scalars(stmt):
        row = reply_row(r)
        lead = s.get(Lead, r.lead_id)
        row.update({"name": lead_row(lead)["name"], "company": lead_row(lead)["company"], "email": lead.contact.email, "score": lead.score})
        out.append(row)
    return out


class ApproveIn(BaseModel):
    body: str | None = Field(default=None, max_length=5000)


@router.post("/inbox/{reply_id}/approve", summary="Approve the draft reply and send it")
def approve_reply(reply_id: int, body: ApproveIn, s: Session = Depends(db), ctx: Ctx = Depends(get_ctx), u: dict = Depends(writer)):
    try:
        status, reason = approve_and_send(s, ctx.effective(s), ctx.adapters, reply_id, decided_by=u["user"], role=u["role"], body=body.body, now=ctx.now(s))
    except ApprovalError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"status": status, "reason": reason}


@router.post("/inbox/{reply_id}/reject", summary="Reject the draft reply")
def reject(reply_id: int, s: Session = Depends(db), u: dict = Depends(writer)):
    try:
        reject_reply(s, reply_id, decided_by=u["user"], role=u["role"])
    except ApprovalError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"ok": True}


class BookIn(BaseModel):
    slot: datetime


@router.get("/inbox/{reply_id}/slots", summary="Open times from the calendar")
def slots(reply_id: int, s: Session = Depends(db), ctx: Ctx = Depends(get_ctx)):
    from datetime import timedelta

    now = ctx.now(s)
    return [t.isoformat() for t in ctx.adapters.calendar.slots(now + timedelta(days=1), now + timedelta(days=8))]


@router.post("/inbox/{reply_id}/book", summary="Book a call from a reply")
def book(reply_id: int, body: BookIn, s: Session = Depends(db), ctx: Ctx = Depends(get_ctx), u: dict = Depends(writer)):
    r = s.get(Reply, reply_id)
    if r is None:
        raise HTTPException(404, "That reply does not exist.")
    guard_write(ctx.effective(s), "calendar.book")
    lead = s.get(Lead, r.lead_id)
    if lead.status in {"suppressed", "dead"} or r.intent in {"unsubscribe", "bounce"}:
        raise HTTPException(409, "This person asked not to be contacted, so no call can be booked.")
    if s.scalars(select(Meeting).where(Meeting.lead_id == lead.id)).first() is not None:
        raise HTTPException(409, "A call is already booked with this lead.")
    c = lead.contact
    b = ctx.adapters.calendar.book(start=body.slot, name=f"{c.first_name} {c.last_name}".strip(), email=c.email, timezone=c.timezone or "UTC")
    s.add(Meeting(lead_id=lead.id, starts_at=b.starts_at, ends_at=b.ends_at, external_id=b.external_id))
    lead.status = "meeting"
    deal = s.scalars(select(Deal).where(Deal.lead_id == lead.id)).first()
    if deal:
        deal.stage = "meeting"
    s.add(Activity(lead_id=lead.id, kind="meeting", summary=f"Call booked for {iso(b.starts_at)}", created_at=ctx.now(s)))
    record_event(s, "meeting.booked", "lead", lead.id, {})
    if r.approval_id is not None and not r.handled:
        # The call is booked, so the drafted reply that offered times is no longer wanted.
        try:
            reject_reply(s, r.id, decided_by=u["user"], role=u["role"], note="Call booked from the inbox")
        except ApprovalError:
            r.handled = True
    r.handled = True
    return {"external_id": b.external_id, "starts_at": iso(b.starts_at)}


@router.get("/pipeline", summary="Deals by stage")
def pipeline(s: Session = Depends(db)):
    return {"stages": list(DEAL_STAGES), "deals": [deal_row(d) for d in s.scalars(select(Deal).order_by(Deal.id))]}


class MoveIn(BaseModel):
    stage: str
    lost_reason: str = Field(default="", max_length=200)


@router.post("/pipeline/{deal_id}/move", summary="Move a deal to another stage")
def move(deal_id: int, body: MoveIn, s: Session = Depends(db), ctx: Ctx = Depends(get_ctx), u: dict = Depends(writer)):
    d = s.get(Deal, deal_id)
    if d is None:
        raise HTTPException(404, "That deal does not exist.")
    if body.stage not in DEAL_STAGES:
        raise HTTPException(422, f"Stage must be one of: {', '.join(DEAL_STAGES)}.")
    old, d.stage = d.stage, body.stage
    lead = d.lead
    if body.stage in {"won", "lost"}:
        d.closed_at = ctx.now(s)
        d.lost_reason = body.lost_reason if body.stage == "lost" else ""
        lead.status = body.stage
        for e in s.scalars(select(Enrollment).where(Enrollment.lead_id == lead.id, Enrollment.status.in_(("active", "paused")))):
            e.status, e.stop_reason, e.next_send_at = "stopped", body.stage, None
    else:
        d.closed_at = None
        if lead.status in {"won", "lost"}:
            lead.status = "replied"
    s.add(Activity(lead_id=lead.id, kind="stage", summary=f"Deal moved from {old} to {body.stage}", created_at=ctx.now(s)))
    record_audit(s, u["user"], "deal.moved", f"deal:{d.id}", {"from": old, "to": body.stage})
    return deal_row(d)
