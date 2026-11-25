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

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from pipecairn import model_tasks, offline_llm
from pipecairn.adapters.base import InboundEmail, InboundSms
from pipecairn.models import Activity, Deal, Enrollment, Lead, Mailbox, Message, Reply, UnmatchedMail
from pipecairn.reply_text import human_part
from pipecairn.replies import MONTHS, classify_reply
from pipecairn.sender import bounce_limits, deliver, maybe_pause_for_bounces
from pipecairn.suppression import add_suppression
from pipecairn.util import aware, normalize_email
from sendora_core.approvals import ROLES_THAT_DECIDE, ApprovalError, decide, request_approval, require_approved
from sendora_core.audit import record_audit
from sendora_core.events import record_event
from sendora_core.llm import LLM
from sendora_core.models import Approval
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


EXTERNAL_ID_MAX = 120  # the width of Message.external_id; Postgres refuses a longer value, so a very long Message-ID is shortened to a stable hash
ADDRESS_MAX = 254


def fit_external_id(ext: str) -> str:
    return ext if len(ext) <= EXTERNAL_ID_MAX else "h-" + hashlib.sha256(ext.encode()).hexdigest()[:40]


def keep_unmatched(session: Session, inbound: InboundEmail, ext: str, now: datetime) -> None:
    """Mail from an address that is not a lead (an alias, a forward, a colleague, a stranger) is not dropped: it is kept where the owner can read it, once."""
    if session.scalars(select(UnmatchedMail).where(UnmatchedMail.external_id == ext)).first() is not None:
        return
    session.add(UnmatchedMail(external_id=ext, from_addr=inbound.from_addr[:ADDRESS_MAX], to_addr=inbound.to_addr[:ADDRESS_MAX], subject=inbound.subject[:300],
                              snippet=human_part(inbound.body[:20000])[:600], created_at=now))
    record_event(session, "reply.unmatched", None, None, {"from": "redacted"})


def capture_email(session: Session, settings: BaseAppSettings, llm: LLM | None, calendar, inbound: InboundEmail, now: datetime) -> Reply | None:
    """Read one inbound email. The sender line proves nothing, so what a message may do depends on what it can prove:
    a request to stop is honoured at once (a wrong stop can be undone by hand, a missed one cannot), but a bounce, which suppresses the address
    and counts against the mailbox, is believed only from a real delivery status report that names a message we sent."""
    ext = fit_external_id(inbound.external_id or content_key(inbound))
    if inbound.is_dsn:
        lead = lead_for_delivery_report(session, inbound.references)
    else:
        lead = find_lead_by_email(session, inbound.from_addr)
        if lead is None:
            lead = lead_for_delivery_report(session, inbound.references)  # an alias or a forward: the reply still names the message of ours it answers
    if lead is None:
        keep_unmatched(session, inbound, ext, now)
        return None
    if session.scalars(select(Message).where(Message.external_id == ext, Message.direction == "in")).first():
        return None  # already captured (polling twice, or a signed webhook sent twice, must not double count)
    msg = Message(lead_id=lead.id, channel="email", direction="in", to_addr=inbound.to_addr[:ADDRESS_MAX], subject=inbound.subject[:300], body=inbound.body[:20000],
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
        # "Mail delivery failed" typed into any email proves nothing. It changes no address, no lead and no mailbox. It also is not hidden: a person may have
        # written "your mail bounced to my spam, happy to talk Tuesday", so it stays open in the Inbox until someone reads it and marks it done.
        reply.suggested_action, reply.handled = "unverified_bounce", False
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


def _set_handled(session: Session, reply_id: int, value: bool, only_if: bool | None = None) -> int:
    """One conditional update, so two clicks at once cannot both win. Returns how many rows changed."""
    stmt = update(Reply).where(Reply.id == reply_id)
    if only_if is not None:
        stmt = stmt.where(Reply.handled.is_(only_if))
    return session.execute(stmt.values(handled=value).execution_options(synchronize_session=False)).rowcount or 0


def approve_and_send(session: Session, settings: BaseAppSettings, adapters, reply_id: int, *, decided_by: str, role: str, body: str | None, now: datetime) -> tuple[str, str]:
    """A person approves the draft (optionally edited), then it goes through the same gates as any send.

    The approval is decided first (one atomic update, so a double click cannot approve twice). When the send does not happen (the daily cap is reached, a quiet
    hour, the vendor failed, a safety check stopped it) the reply stays open and the approval stays "approved", so approving again simply tries again."""
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
    approval = session.get(Approval, reply.approval_id)
    if approval is None:
        raise ApprovalError("This reply has no draft waiting for approval.")
    again = approval.status == "approved" and not reply.handled
    if approval.status == "pending":
        decide(session, reply.approval_id, True, decided_by, role)
    elif again:
        if role not in ROLES_THAT_DECIDE:
            raise ApprovalError("Only an owner or an approver can send.")
    else:
        raise ApprovalError(f"Approval {approval.id} was already {approval.status}.")
    require_approved(session, reply.approval_id, "reply.send")
    if _set_handled(session, reply.id, True, only_if=False) != 1:
        raise ApprovalError("This reply was already sent.")  # a second click at the same moment lost the claim
    lead = session.get(Lead, reply.lead_id)
    status, reason = deliver(session, settings, adapters, lead=lead, enr=None, channel=reply.message.channel, subject=("Re: " + reply.message.subject)[:300], body=text, now=now, respect_quiet=False)
    done = status in {"sent", "drafted"}
    if not done:
        _set_handled(session, reply.id, False)  # still open: the person can try again, or reject it
    session.refresh(reply)
    record_audit(session, decided_by, "reply.sent_again" if again else "reply.approved", f"reply:{reply.id}", {"result": status, "reason": reason})
    if done:
        session.add(Activity(lead_id=lead.id, kind="message", summary="Approved reply " + ("sent" if status == "sent" else "saved as a draft (draft mode)"), created_at=now))
    return status, reason


def reject_reply(session: Session, reply_id: int, *, decided_by: str, role: str, note: str = "") -> None:
    """Reject a draft that is waiting, or dismiss one that was approved but could not be sent (it can never be sent now, so it is closed as rejected)."""
    reply = session.get(Reply, reply_id)
    if reply is None or reply.approval_id is None:
        raise ApprovalError("This reply has no draft waiting for approval.")
    approval = session.get(Approval, reply.approval_id)
    if approval is not None and approval.status == "approved" and not reply.handled:
        if role not in ROLES_THAT_DECIDE:
            raise ApprovalError("Only an owner or an approver can decide.")
        session.execute(update(Approval).where(Approval.id == approval.id, Approval.status == "approved")
                        .values(status="rejected", decided_by=decided_by, decision_note=(note or "Dismissed: it was approved but could not be sent.")[:500]).execution_options(synchronize_session=False))
        record_audit(session, decided_by, "approval.rejected", f"approval:{approval.id}", {"note": note, "after_approval": True})
    else:
        decide(session, reply.approval_id, False, decided_by, role, note)
    _set_handled(session, reply.id, True)
    session.refresh(reply)


def dismiss_reply(session: Session, reply_id: int, *, decided_by: str) -> None:
    """Mark a reply that needs no draft (an unverified bounce, an answer already handled by hand) as read. It never sends anything."""
    reply = session.get(Reply, reply_id)
    if reply is None:
        raise ApprovalError("That reply does not exist.")
    if reply.approval_id is not None and not reply.handled:
        raise ApprovalError("This reply has a draft waiting. Approve or reject it instead.")
    _set_handled(session, reply.id, True)
    record_audit(session, decided_by, "reply.dismissed", f"reply:{reply.id}", {})
