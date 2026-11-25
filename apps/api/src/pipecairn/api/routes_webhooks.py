"""Signed webhooks. Nothing here uses a session: each one checks its own signature first and refuses everything else."""

from __future__ import annotations

import hashlib
import hmac
import json
import time

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from pipecairn import inbox, intake
from pipecairn.adapters.base import InboundEmail
from pipecairn.adapters.calcom import verify_calcom_webhook
from pipecairn.adapters.telnyx import parse_inbound, verify_telnyx_webhook
from pipecairn.api.deps import db, get_ctx
from pipecairn.context import Ctx
from pipecairn.models import Activity, Deal, Lead, Meeting
from pipecairn.suppression import suppress_everywhere
from pipecairn.unsubscribe import read_token
from pipecairn.util import clean_person_text
from sendora_core.adapters import AdapterError
from sendora_core.audit import record_audit
from sendora_core.auth import verify_webhook_signature
from sendora_core.events import record_event

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])
MAX_BODY = 1_000_000
REPLAY_WINDOW_SECONDS = 300


async def body_of(request: Request) -> bytes:
    """The body, read with a ceiling. A declared length over the limit is refused before a byte is read, and a body that lies about its
    length (or has none, chunked) is counted while it arrives and cut off at the limit."""
    declared = request.headers.get("content-length")
    if declared is not None and (not declared.isdigit() or int(declared) > MAX_BODY):
        raise HTTPException(413, "Body too large.")
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > MAX_BODY:
            raise HTTPException(413, "Body too large.")
        chunks.append(chunk)
    return b"".join(chunks)


async def raw_body(request: Request) -> bytes:
    """The bounded body as a dependency. Reading the body is the only part that has to wait on the network, so it runs on the event loop; the route that
    uses it is a plain function that runs on a worker thread, so a slow database call or a model call cannot freeze every other request."""
    return await body_of(request)


def check_shared(ctx: Ctx, raw: bytes, sig: str | None, timestamp: str | None = None, now: float | None = None) -> None:
    """Signature check for the shared secret webhooks. A sender that adds an `x-timestamp` header (seconds since 1970) signs `timestamp.body`
    and a captured request stops working after five minutes. Without the header the body alone is signed, and the receiver drops a message it has already stored."""
    secret = ctx.settings.webhook_shared_secret
    if not secret or not sig:
        raise HTTPException(401, "Bad signature.")
    signed = raw
    if timestamp is not None:
        try:
            when = int(timestamp)
        except ValueError:
            raise HTTPException(401, "Bad signature.") from None
        if abs((now if now is not None else time.time()) - when) > REPLAY_WINDOW_SECONDS:
            raise HTTPException(401, "This request is too old or its clock is wrong.")
        signed = timestamp.encode() + b"." + raw
    if not verify_webhook_signature(secret, signed, sig):
        raise HTTPException(401, "Bad signature.")


@router.post("/telnyx", summary="Inbound text from Telnyx (Ed25519 signed)")
def telnyx(raw: bytes = Depends(raw_body), s: Session = Depends(db), ctx: Ctx = Depends(get_ctx), telnyx_signature_ed25519: str | None = Header(default=None), telnyx_timestamp: str | None = Header(default=None)):
    if not (telnyx_signature_ed25519 and telnyx_timestamp and verify_telnyx_webhook(ctx.settings.telnyx_public_key, raw, telnyx_signature_ed25519, telnyx_timestamp)):
        raise HTTPException(401, "Bad signature.")
    try:
        sms = parse_inbound(json.loads(raw))
    except (AdapterError, KeyError, ValueError) as exc:
        return {"ok": True, "ignored": True}
    r = inbox.capture_sms(s, ctx.effective(s), ctx.llm(s), ctx.adapters.calendar, sms, ctx.now(s))
    return {"ok": True, "captured": r is not None}


@router.post("/calcom", summary="Booking events from Cal.com (HMAC signed)")
def calcom(raw: bytes = Depends(raw_body), s: Session = Depends(db), ctx: Ctx = Depends(get_ctx), x_cal_signature_256: str | None = Header(default=None)):
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
    uid = str(p.get("uid", "")) or "h-" + hashlib.sha256(raw).hexdigest()[:40]  # a booking with no id is still stored once
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
def email(raw: bytes = Depends(raw_body), s: Session = Depends(db), ctx: Ctx = Depends(get_ctx), x_signature: str | None = Header(default=None), x_timestamp: str | None = Header(default=None)):
    check_shared(ctx, raw, x_signature, x_timestamp)
    try:
        d = json.loads(raw)
        refs = d.get("references") or []
        inb = InboundEmail(external_id=str(d.get("message_id") or ""), from_addr=str(d["from"]), to_addr=str(d.get("to", "")), subject=str(d.get("subject", "")), body=str(d.get("text", "")),
                           is_dsn=d.get("dsn") is True, references=tuple(str(r) for r in refs[:20]) if isinstance(refs, list) else (), auth_results=str(d.get("authentication_results", ""))[:300])
    except (KeyError, ValueError, AttributeError, TypeError):
        raise HTTPException(422, "Expected JSON with from, to, subject, text and message_id.") from None
    r = inbox.capture_email(s, ctx.effective(s), ctx.llm(s), ctx.adapters.calendar, inb, ctx.now(s))
    return {"ok": True, "captured": r is not None}


@router.post("/form", summary="A web form lead (HMAC signed)")
def form(raw: bytes = Depends(raw_body), s: Session = Depends(db), ctx: Ctx = Depends(get_ctx), x_signature: str | None = Header(default=None), x_timestamp: str | None = Header(default=None)):
    check_shared(ctx, raw, x_signature, x_timestamp)
    try:
        d = json.loads(raw)
        row = {k: str(d.get(k, "")) for k in intake.CSV_COLUMNS if k != "sms_consent"}
        for k in ("first_name", "last_name", "title"):
            row[k] = clean_person_text(row[k])  # these go into the first email, so anything that is not a plain name is dropped
        row["sms_consent"] = "yes" if d.get("sms_consent") is True else ""
        if not row["email"]:
            raise ValueError
    except (ValueError, AttributeError):
        raise HTTPException(422, "Expected JSON with at least an email.") from None
    now = ctx.now(s)
    rep = intake.import_leads(s, [row], now, default_source="form", default_timezone=ctx.settings.default_timezone)
    from pipecairn.jobs import job_enrich, job_score

    job_enrich(s, ctx), job_score(s, ctx)
    return {"ok": True, "created": rep.created, "duplicates": rep.duplicates}


PAGE = "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"><title>{title}</title></head><body style=\"font-family:system-ui,sans-serif;max-width:32rem;margin:4rem auto;padding:0 1rem\"><h1>{title}</h1>{body}</body></html>"


@router.get("/unsubscribe/{token}", response_class=HTMLResponse, summary="The page behind the unsubscribe link in an email (asks for one click to confirm)")
def unsubscribe_page(token: str, ctx: Ctx = Depends(get_ctx)):
    """Opening a link must not change anything (mail scanners open links), so this only shows the button."""
    if read_token(ctx.settings.session_secret, token, ctx.settings.session_secret_previous) is None:
        return HTMLResponse(PAGE.format(title="This link is not valid", body="<p>Reply STOP to the email instead and we will remove you.</p>"), status_code=404)
    return HTMLResponse(PAGE.format(title="Stop these emails?", body=f"<form method=\"post\" action=\"/api/webhooks/unsubscribe/{token}\"><button type=\"submit\">Yes, stop emailing me</button></form>"))


@router.post("/unsubscribe/{token}", summary="One click unsubscribe from the List-Unsubscribe header (signed link, no session)")
def unsubscribe(token: str, s: Session = Depends(db), ctx: Ctx = Depends(get_ctx)):
    """A mail program (or the page above) posts here. The signed address is suppressed at once and its leads stop."""
    addr = read_token(ctx.settings.session_secret, token, ctx.settings.session_secret_previous)
    if addr is None:
        raise HTTPException(404, "This link is not valid.")
    stopped = suppress_everywhere(s, "email", addr, "asked to stop (unsubscribe link)", "unsubscribe_link")
    record_audit(s, "system", "suppression.from_unsubscribe_link", None, {"leads_stopped": stopped})
    return {"ok": True}
