"""Signed webhooks. Nothing here uses a session: each one checks its own signature first and refuses everything else."""

from __future__ import annotations

import hashlib
import hmac
import json

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from pipecairn import inbox, intake
from pipecairn.adapters.base import InboundEmail
from pipecairn.adapters.calcom import verify_calcom_webhook
from pipecairn.adapters.telnyx import parse_inbound, verify_telnyx_webhook
from pipecairn.api.deps import db, get_ctx
from pipecairn.context import Ctx
from pipecairn.models import Activity, Deal, Lead, Meeting
from sendora_core.adapters import AdapterError
from sendora_core.auth import verify_webhook_signature
from sendora_core.events import record_event

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])
MAX_BODY = 1_000_000


async def body_of(request: Request) -> bytes:
    raw = await request.body()
    if len(raw) > MAX_BODY:
        raise HTTPException(413, "Body too large.")
    return raw


def check_shared(ctx: Ctx, raw: bytes, sig: str | None) -> None:
    if not ctx.settings.webhook_shared_secret or not sig or not verify_webhook_signature(ctx.settings.webhook_shared_secret, raw, sig):
        raise HTTPException(401, "Bad signature.")


@router.post("/telnyx", summary="Inbound text from Telnyx (Ed25519 signed)")
async def telnyx(request: Request, s: Session = Depends(db), ctx: Ctx = Depends(get_ctx), telnyx_signature_ed25519: str | None = Header(default=None), telnyx_timestamp: str | None = Header(default=None)):
    raw = await body_of(request)
    if not (telnyx_signature_ed25519 and telnyx_timestamp and verify_telnyx_webhook(ctx.settings.telnyx_public_key, raw, telnyx_signature_ed25519, telnyx_timestamp)):
        raise HTTPException(401, "Bad signature.")
    try:
        sms = parse_inbound(json.loads(raw))
    except (AdapterError, KeyError, ValueError) as exc:
        return {"ok": True, "ignored": True}
    r = inbox.capture_sms(s, ctx.effective(s), ctx.llm(s), ctx.adapters.calendar, sms, ctx.now(s))
    return {"ok": True, "captured": r is not None}


@router.post("/calcom", summary="Booking events from Cal.com (HMAC signed)")
async def calcom(request: Request, s: Session = Depends(db), ctx: Ctx = Depends(get_ctx), x_cal_signature_256: str | None = Header(default=None)):
    raw = await body_of(request)
    if not verify_calcom_webhook(ctx.settings.calcom_webhook_secret, raw, x_cal_signature_256 or ""):
        raise HTTPException(401, "Bad signature.")
    try:
        ev = json.loads(raw)
        p = ev["payload"]
        email = (p.get("attendees") or [{}])[0].get("email", "")
    except (KeyError, ValueError):
        return {"ok": True, "ignored": True}
    if ev.get("triggerEvent") != "BOOKING_CREATED":
        return {"ok": True, "ignored": True}
    lead = inbox.find_lead_by_email(s, email)
    uid = str(p.get("uid", ""))
    if lead is None or s.scalars(select(Meeting).where(Meeting.external_id == uid)).first():
        return {"ok": True, "ignored": True}
    from datetime import datetime

    st = datetime.fromisoformat(p["startTime"].replace("Z", "+00:00"))
    en = datetime.fromisoformat(p["endTime"].replace("Z", "+00:00"))
    s.add(Meeting(lead_id=lead.id, starts_at=st, ends_at=en, external_id=uid))
    lead.status = "meeting"
    deal = s.scalars(select(Deal).where(Deal.lead_id == lead.id)).first()
    if deal:
        deal.stage = "meeting"
    s.add(Activity(lead_id=lead.id, kind="meeting", summary="Call booked through Cal.com", created_at=ctx.now(s)))
    record_event(s, "meeting.booked", "lead", lead.id, {"via": "calcom"})
    return {"ok": True, "captured": True}


@router.post("/email", summary="Inbound email relayed by your mail provider (HMAC signed)")
async def email(request: Request, s: Session = Depends(db), ctx: Ctx = Depends(get_ctx), x_signature: str | None = Header(default=None)):
    raw = await body_of(request)
    check_shared(ctx, raw, x_signature)
    try:
        d = json.loads(raw)
        inb = InboundEmail(external_id=str(d.get("message_id") or ""), from_addr=str(d["from"]), to_addr=str(d.get("to", "")), subject=str(d.get("subject", "")), body=str(d.get("text", "")))
    except (KeyError, ValueError):
        raise HTTPException(422, "Expected JSON with from, to, subject, text and message_id.") from None
    r = inbox.capture_email(s, ctx.effective(s), ctx.llm(s), ctx.adapters.calendar, inb, ctx.now(s))
    return {"ok": True, "captured": r is not None}


@router.post("/form", summary="A web form lead (HMAC signed)")
async def form(request: Request, s: Session = Depends(db), ctx: Ctx = Depends(get_ctx), x_signature: str | None = Header(default=None)):
    raw = await body_of(request)
    check_shared(ctx, raw, x_signature)
    try:
        d = json.loads(raw)
        row = {k: str(d.get(k, "")) for k in intake.CSV_COLUMNS if k != "sms_consent"}
        row["sms_consent"] = "yes" if d.get("sms_consent") is True else ""
        if not row["email"]:
            raise ValueError
    except (ValueError, AttributeError):
        raise HTTPException(422, "Expected JSON with at least an email.") from None
    now = ctx.now(s)
    rep = intake.import_leads(s, [row], now, default_source="form")
    from pipecairn.jobs import job_enrich, job_score

    job_enrich(s, ctx), job_score(s, ctx)
    return {"ok": True, "created": rep.created, "duplicates": rep.duplicates}
