"""Inbox: capture an inbound message, read it, act on it, and send an approved reply.

Rules about acting:
- unsubscribe, bounce: act at once, no message goes out (stop and suppress).
- everything that would send a message goes to the approval queue first.
- the text of a reply is data. It can never trigger a tool call.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from pipecairn import model_tasks, offline_llm
from pipecairn.adapters.base import InboundEmail, InboundSms
from pipecairn.models import Activity, Deal, Enrollment, Lead, Mailbox, Message, Reply
from pipecairn.replies import MONTHS, classify_reply
from pipecairn.sender import bounce_limits, deliver, maybe_pause_for_bounces
from pipecairn.suppression import add_suppression
from pipecairn.util import aware, normalize_email
from sendora_core.approvals import ApprovalError, decide, request_approval, require_approved
from sendora_core.audit import record_audit
from sendora_core.events import record_event
from sendora_core.llm import LLM
from sendora_core.settings import BaseAppSettings

PLACEHOLDER = "[[FILL IN"


def _stop_enrollments(session: Session, lead_id: int, reason: str) -> None:
    for e in session.scalars(select(Enrollment).where(Enrollment.lead_id == lead_id, Enrollment.status.in_(("active", "paused")))):
        e.status, e.stop_reason, e.next_send_at, e.paused_until = "stopped", reason, None, None


def parse_return_date(text: str, now: datetime, default_days: int) -> datetime:
    """A best effort reading of 'until the 14th', 'in January', 'in 3 months'. Falls back to a default."""
    t = text.lower()
    now = aware(now)
    m = re.search(r"\b(?:in|after)\s+(\d{1,2})\s+months?\b", t)
    if m:
        return now + timedelta(days=30 * int(m.group(1)))
    for name, num in MONTHS.items():
        if re.search(rf"\b{name}\b", t):
            year = now.year + (1 if num <= now.month else 0)
            return datetime(year, num, 1, tzinfo=UTC)
    m = re.search(r"until (?:the )?(\d{1,2})(?:st|nd|rd|th)\b", t)
    if m:
        day = int(m.group(1))
        cand = now.replace(day=min(day, 28), hour=0, minute=0, second=0, microsecond=0)
        return cand if cand > now else (cand.replace(month=cand.month % 12 + 1, year=cand.year + (cand.month == 12)))
    if "next week" in t or "on monday" in t:
        return now + timedelta(days=7)
    if "next quarter" in t:
        return now + timedelta(days=90)
    return now + timedelta(days=default_days)


def find_lead_by_email(session: Session, addr: str) -> Lead | None:
    from pipecairn.models import Contact

    c = session.scalars(select(Contact).where(Contact.email == normalize_email(addr))).first()
    return session.scalars(select(Lead).where(Lead.contact_id == c.id)).first() if c else None


def _message_id(raw: str) -> str:
    return raw.strip().strip("<>").strip().lower()


def lead_for_delivery_report(session: Session, references: tuple[str, ...]) -> Lead | None:
    """The lead whose outbound message a delivery failure notice names. Matching is by the Message-ID we wrote, never by an address in the text."""
    ids = {_message_id(r) for r in references if r.strip()}
    if not ids:
        return None
    for m in session.scalars(select(Message).where(Message.direction == "out", Message.status == "sent", Message.external_id != "").order_by(Message.id.desc()).limit(5000)):
        if _message_id(m.external_id) in ids:
            return session.get(Lead, m.lead_id)
    return None


def content_key(inbound: InboundEmail) -> str:
    """A stable id for a message that came without a Message-ID, so the same signed message sent twice is stored once."""
    raw = "\x1f".join((inbound.from_addr.lower(), inbound.to_addr.lower(), inbound.subject, inbound.body))
    return "h-" + hashlib.sha256(raw.encode()).hexdigest()[:40]


def capture_email(session: Session, settings: BaseAppSettings, llm: LLM | None, calendar, inbound: InboundEmail, now: datetime) -> Reply | None:
    """Read one inbound email. The sender line proves nothing, so what a message may do depends on what it can prove:
    a request to stop is honoured at once (a wrong stop can be undone by hand, a missed one cannot), but a bounce, which suppresses the address
    and counts against the mailbox, is believed only from a real delivery status report that names a message we sent."""
    if inbound.is_dsn:
        lead = lead_for_delivery_report(session, inbound.references)
    else:
        lead = find_lead_by_email(session, inbound.from_addr)
    if lead is None:
        record_event(session, "reply.unmatched", None, None, {"from": "redacted"})
        return None
    ext = inbound.external_id or content_key(inbound)
    if session.scalars(select(Message).where(Message.external_id == ext, Message.direction == "in")).first():
        return None  # already captured (polling twice, or a signed webhook sent twice, must not double count)
    msg = Message(lead_id=lead.id, channel="email", direction="in", to_addr=inbound.to_addr, subject=inbound.subject[:300], body=inbound.body[:20000],
                  status="received", external_id=ext, created_at=now, sent_at=inbound.received_at or now)
    session.add(msg)
    session.flush()
    return _read_and_act(session, settings, llm, calendar, lead, msg, now, bounce_verified=inbound.is_dsn, auth_note=(inbound.auth_results or "none")[:300])


def capture_sms(session: Session, settings: BaseAppSettings, llm: LLM | None, calendar, inbound: InboundSms, now: datetime) -> Reply | None:
    from pipecairn.models import Contact

    c = session.scalars(select(Contact).where(Contact.phone == inbound.from_number)).first()
    lead = session.scalars(select(Lead).where(Lead.contact_id == c.id)).first() if c else None
    if lead is None:
        return None
    if session.scalars(select(Message).where(Message.external_id == inbound.external_id, Message.direction == "in")).first():
        return None
    msg = Message(lead_id=lead.id, channel="sms", direction="in", to_addr=inbound.to_number, body=inbound.text[:2000], status="received",
                  external_id=inbound.external_id, created_at=now, sent_at=now)
    session.add(msg)
    session.flush()
    return _read_and_act(session, settings, llm, calendar, lead, msg, now)


def _read_and_act(session: Session, settings: BaseAppSettings, llm: LLM | None, calendar, lead: Lead, msg: Message, now: datetime, *, bounce_verified: bool = False, auth_note: str = "") -> Reply:
    cls = classify_reply(msg.body, llm, msg.subject or "")
    reply = Reply(message_id=msg.id, lead_id=lead.id, intent=cls.intent, confidence=cls.confidence, summary=cls.summary, created_at=now)
    session.add(reply)
    session.flush()
    record_event(session, "reply.classified", "reply", reply.id, {"intent": cls.intent, "source": cls.source})
    session.add(Activity(lead_id=lead.id, kind="reply", summary=f"Reply read as {cls.intent}", created_at=now))
    deal = session.scalars(select(Deal).where(Deal.lead_id == lead.id)).first()
    c = lead.contact
    i = cls.intent
    if i == "unsubscribe":
        add_suppression(session, "email", c.email, "asked to stop (reply)", "reply")
        if msg.channel == "sms" and c.phone:
            add_suppression(session, "phone", c.phone, "asked to stop (text)", "reply")
        _stop_enrollments(session, lead.id, "unsubscribe")
        lead.status = "suppressed"
        reply.suggested_action, reply.handled = "suppressed", True
        # Mail can be forged, so the owner can see how the sender was checked and undo a wrong stop by hand.
        record_audit(session, "system", "suppression.from_reply", f"lead:{lead.id}", {"channel": msg.channel, "authentication": auth_note or "not available"})
    elif i == "bounce" and not bounce_verified:
        # "Mail delivery failed" typed into any email proves nothing. It changes no address, no lead and no mailbox. The owner can read it in the Inbox.
        reply.suggested_action, reply.handled = "unverified_bounce", True
        record_audit(session, "system", "bounce.not_verified", f"reply:{reply.id}", {"authentication": auth_note or "not available"})
    elif i == "bounce":
        add_suppression(session, "email", c.email, "bounced", "reply")
        _stop_enrollments(session, lead.id, "bounce")
        lead.status = "dead"
        last = session.scalars(select(Message).where(Message.lead_id == lead.id, Message.direction == "out", Message.status == "sent", Message.mailbox_id.is_not(None)).order_by(Message.id.desc())).first()
        if last and last.mailbox_id:
            mb = session.get(Mailbox, last.mailbox_id)
            if mb:
                mb.bounce_count += 1
                maybe_pause_for_bounces(mb, *bounce_limits(settings))
        reply.suggested_action, reply.handled = "suppressed", True
    elif i == "out_of_office":
        until = parse_return_date(msg.body, now, 7)
        for e in session.scalars(select(Enrollment).where(Enrollment.lead_id == lead.id, Enrollment.status == "active")):
            e.status, e.paused_until, e.next_send_at = "paused", until, None
        reply.suggested_action, reply.handled, reply.return_on = "wait", True, until.date().isoformat()
    elif i == "not_now":
        until = parse_return_date(msg.body, now, 90)
        for e in session.scalars(select(Enrollment).where(Enrollment.lead_id == lead.id, Enrollment.status == "active")):
            e.status, e.paused_until, e.next_send_at = "paused", until, None
        reply.suggested_action, reply.handled, reply.return_on = "snooze", True, until.date().isoformat()
        if deal and deal.stage in {"new", "contacted"}:
            deal.stage = "replied"
    else:
        _stop_enrollments(session, lead.id, i)
        lead.status = "replied"
        if deal and deal.stage in {"new", "contacted"}:
            deal.stage = "replied"
        slots = []
        if i == "interested" and calendar is not None:
            try:
                slots = [s.strftime("%A %d %B, %H:%M UTC") for s in calendar.slots(aware(now) + timedelta(days=1), aware(now) + timedelta(days=7))]
            except Exception:
                slots = []
        reply.suggested_action = {"interested": "book_call", "question": "answer_question", "wrong_person": "ask_referral"}[i]
        sender = getattr(settings, "sender_name", "Alex")
        reply.draft_reply = model_tasks.write_draft(llm, i, c.first_name, slots, msg.body, offline_llm.draft_text(i, c.first_name, slots, sender), sender)
        ap = request_approval(session, "reply.send", f"Reply to {c.first_name} {c.last_name} ({i})", {"reply_id": reply.id, "lead_id": lead.id}, "medium", "system")
        reply.approval_id = ap.id
    session.flush()
    return reply


def approve_and_send(session: Session, settings: BaseAppSettings, adapters, reply_id: int, *, decided_by: str, role: str, body: str | None, now: datetime) -> tuple[str, str]:
    """A person approves the draft (optionally edited), then it goes through the same gates as any send."""
    reply = session.get(Reply, reply_id)
    if reply is None or reply.approval_id is None:
        raise ApprovalError("This reply has no draft waiting for approval.")
    if settings.kill_switch:
        raise ApprovalError("The kill switch is on, so nothing can be approved or sent. Turn it off first, then approve.")
    text = body if body is not None else reply.draft_reply
    if not text.strip():
        raise ApprovalError("The reply is empty. Write a message, or reject the draft, before you approve.")
    if PLACEHOLDER in text:
        raise ApprovalError("The draft still has a [[FILL IN]] part. Write that part, then approve.")
    decide(session, reply.approval_id, True, decided_by, role)
    require_approved(session, reply.approval_id, "reply.send")
    lead = session.get(Lead, reply.lead_id)
    status, reason = deliver(session, settings, adapters, lead=lead, enr=None, channel=reply.message.channel, subject=("Re: " + reply.message.subject)[:300], body=text, now=now, respect_quiet=False)
    reply.handled = status in {"sent", "drafted"}
    record_audit(session, decided_by, "reply.approved", f"reply:{reply.id}", {"result": status, "reason": reason})
    if status in {"sent", "drafted"}:
        session.add(Activity(lead_id=lead.id, kind="message", summary="Approved reply " + ("sent" if status == "sent" else "saved as a draft (draft mode)"), created_at=now))
    return status, reason


def reject_reply(session: Session, reply_id: int, *, decided_by: str, role: str, note: str = "") -> None:
    reply = session.get(Reply, reply_id)
    if reply is None or reply.approval_id is None:
        raise ApprovalError("This reply has no draft waiting for approval.")
    decide(session, reply.approval_id, False, decided_by, role, note)
    reply.handled = True
