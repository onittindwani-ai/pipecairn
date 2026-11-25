from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pipecairn import metrics
from pipecairn.audit_check import DEFAULT_LIMIT, verify_recent
from pipecairn.api.deps import db, get_ctx, owner, writer
from pipecairn.api.serializers import iso
from pipecairn.context import Ctx, set_state
from pipecairn.models import Mailbox, Reply
from pipecairn.registry import CATEGORIES, ENV_VARS
from pipecairn.sender import resume_mailbox
from sendora_core.approvals import ApprovalError, decide
from sendora_core.audit import record_audit
from sendora_core.models import Approval, AuditEntry, Event

router = APIRouter(prefix="/api", tags=["operations"])


@router.get("/deliverability", summary="Mailbox health, caps and bounce rates")
def deliverability(s: Session = Depends(db, scope="function")):
    return metrics.deliverability(s)


@router.post("/deliverability/{mailbox_id}/resume", summary="Resume a paused mailbox (owner only)")
def resume(mailbox_id: int, s: Session = Depends(db, scope="function"), u: dict = Depends(owner)):
    mb = s.get(Mailbox, mailbox_id)
    if mb is None:
        raise HTTPException(404, "That mailbox does not exist.")
    resume_mailbox(mb)
    record_audit(s, u["user"], "mailbox.resumed", f"mailbox:{mb.id}", {})
    return {"ok": True}


def approval_row(a: Approval, reply: Reply | None = None) -> dict:
    """`draft` is the text that will go out when a reply approval is approved, so the person deciding reads what they approve. `reply_open` is true while an approved
    reply has not gone out yet (the daily cap, a quiet hour, a vendor error): it can be sent again or dismissed."""
    return {"id": a.id, "action": a.action, "summary": a.summary, "risk": a.risk, "status": a.status, "requested_by": a.requested_by, "decided_by": a.decided_by, "note": a.decision_note,
            "created_at": iso(a.created_at), "payload": a.payload, "draft": reply.draft_reply if reply is not None else "", "reply_id": reply.id if reply is not None else None,
            "reply_open": bool(reply is not None and not reply.handled)}


@router.get("/approvals", summary="Pending and recent approvals")
def approvals(s: Session = Depends(db, scope="function")):
    rows = list(s.scalars(select(Approval).order_by(Approval.id.desc()).limit(100)))
    by_approval = {r.approval_id: r for r in s.scalars(select(Reply).where(Reply.approval_id.in_([a.id for a in rows if a.action == "reply.send"] or [0])))}
    return [approval_row(a, by_approval.get(a.id)) for a in rows]


class DecideIn(BaseModel):
    approve: bool
    note: str = Field(default="", max_length=500)


@router.post("/approvals/{approval_id}/decide", summary="Approve or reject")
def decide_approval(approval_id: int, body: DecideIn, s: Session = Depends(db, scope="function"), ctx: Ctx = Depends(get_ctx), u: dict = Depends(writer)):
    from pipecairn.inbox import approve_and_send, reject_reply

    a = s.get(Approval, approval_id)
    if a is None:
        raise HTTPException(404, "That approval does not exist.")
    try:
        if a.action == "reply.send" and a.payload.get("reply_id"):
            rid = int(a.payload["reply_id"])
            if body.approve:
                status, reason = approve_and_send(s, ctx.effective(s), ctx.adapters, rid, decided_by=u["user"], role=u["role"], body=None, now=ctx.now(s))
                return {"status": status, "reason": reason}
            reject_reply(s, rid, decided_by=u["user"], role=u["role"], note=body.note)
            return {"status": "rejected"}
        decide(s, approval_id, body.approve, u["user"], u["role"], body.note or None)
    except ApprovalError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"status": "approved" if body.approve else "rejected"}


@router.get("/events/latest", summary="The id of the newest event, so the live stream can start after it instead of replaying the history")
def latest_event(s: Session = Depends(db, scope="function")):
    return {"id": int(s.scalar(select(func.max(Event.id))) or 0)}


@router.get("/audit", summary="Audit log, newest first")
def audit(limit: int = Query(100, ge=1, le=1000), s: Session = Depends(db, scope="function")):
    rows = s.scalars(select(AuditEntry).order_by(AuditEntry.id.desc()).limit(limit))
    return [{"id": e.id, "actor": e.actor, "action": e.action, "target": e.target, "detail": e.detail, "at": e.created_at} for e in rows]


@router.get("/audit/verify", summary="Check the audit chain has not been edited (the newest rows; limit=0 checks every row)")
def audit_verify(limit: int = Query(DEFAULT_LIMIT, ge=0, le=5_000_000), s: Session = Depends(db, scope="function")):
    ok, bad, checked = verify_recent(s, limit)
    return {"ok": ok, "first_bad_id": bad, "checked": checked}


@router.get("/integrations", summary="Every adapter, which one is selected, and what it needs")
def integrations(ctx: Ctx = Depends(get_ctx)):
    s = ctx.settings
    chosen = {"email": s.email_adapter, "sms": s.sms_adapter, "calendar": s.calendar_adapter, "crm": s.crm_adapter, "esign": s.esign_adapter}
    out = []
    for row in ctx.registry.describe():
        env = ENV_VARS.get((row["category"], row["name"]), [])
        out.append({**row, "selected": chosen.get(row["category"]) == row["name"], "env_vars": env, "configured": all(bool(getattr(s, v.lower(), "")) for v in env) if env else True})
    return {"categories": list(CATEGORIES), "adapters": out, "demo_mode": s.demo_mode}


@router.post("/integrations/{category}/test", summary="Test the selected adapter in a category")
def test_integration(category: str, ctx: Ctx = Depends(get_ctx), u: dict = Depends(writer)):
    if category not in CATEGORIES:
        raise HTTPException(404, "Unknown category.")
    adapter = getattr(ctx.adapters, category)
    ok, detail = adapter.healthcheck()
    return {"category": category, "ok": ok, "detail": detail}


@router.get("/settings", summary="Mode, kill switch and config problems")
def get_settings(s: Session = Depends(db, scope="function"), ctx: Ctx = Depends(get_ctx)):
    eff = ctx.effective(s)
    return {"mode": ctx.settings.mode.value, "effective_mode": eff.mode.value, "kill_switch": eff.kill_switch, "demo_mode": ctx.settings.demo_mode, "problems": ctx.settings.problems(),
            "quiet_hours": f"{ctx.settings.quiet_end_hour:02d}:00 to {ctx.settings.quiet_start_hour:02d}:00 local", "weekends": ctx.settings.send_weekends}


class SettingsIn(BaseModel):
    kill_switch: bool | None = None
    force_draft: bool | None = None


@router.post("/settings", summary="Turn the kill switch or draft mode on or off (owner only). The app can never switch live sending on.")
def post_settings(body: SettingsIn, s: Session = Depends(db, scope="function"), ctx: Ctx = Depends(get_ctx), u: dict = Depends(owner)):
    if body.kill_switch is not None:
        set_state(s, "kill_switch", "1" if body.kill_switch else "0")
        record_audit(s, u["user"], "settings.kill_switch", None, {"on": body.kill_switch})
    if body.force_draft is not None:
        set_state(s, "force_draft", "1" if body.force_draft else "0")
        record_audit(s, u["user"], "settings.force_draft", None, {"on": body.force_draft})
    s.flush()
    return get_settings(s, ctx)
