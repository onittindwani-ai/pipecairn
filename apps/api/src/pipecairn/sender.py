"""The send engine. Every real world send passes the same gates, in this order, every time:

kill switch, lead status (stop rules), suppression, address checks, customer check, channel consent, quiet hours in the
contact's own time zone, a mailbox with room under its daily cap, and finally the mode (draft mode writes a draft and sends nothing).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from pipecairn import timing
from pipecairn.adapters.base import RecipientRefused, SendUnconfirmed
from pipecairn.models import Activity, Deal, Enrollment, Lead, Mailbox, Message
from pipecairn.suppression import add_suppression, suppression_reason
from pipecairn.templating import TemplateError, render
from pipecairn.unsubscribe import with_footer
from pipecairn.util import aware, is_e164, is_valid_email, normalize_email
from sendora_core.audit import record_audit
from sendora_core.events import record_event, record_metric
from sendora_core.safety import SafetyError, would_write
from sendora_core.settings import BaseAppSettings

STOP_STATUSES = {"replied", "meeting", "proposal", "won", "lost", "suppressed", "dead"}
BOUNCE_RATE_PAUSE = 0.05
MIN_SENDS_FOR_BOUNCE_CHECK = 20
MAX_SEND_ATTEMPTS = 3  # one step is tried this many times (an hour apart) when the mail server refuses the message itself; then the lead is stopped for a person to look at
STEP_COUNTED = ";step_counted"  # added to an unconfirmed message's blocked_reason once its sequence step has been counted as done, so that happens exactly once
SERVER_PROBLEM = "server:"  # blocked_reason prefix for a failure that is the mail server's or the mailbox's (login, certificate, connection): it is retried, but never counts toward the limit


@dataclass
class TickReport:
    sent: int = 0
    drafted: int = 0
    deferred: int = 0
    blocked: int = 0
    stopped: int = 0
    halted: bool = False
    reasons: dict[str, int] = field(default_factory=dict)

    def why(self, reason: str) -> None:
        self.reasons[reason] = self.reasons.get(reason, 0) + 1


def reset_mailbox_day(mb: Mailbox, now: datetime) -> None:
    day = now.date().isoformat()
    if mb.sent_day != day:
        mb.sent_day, mb.sent_today = day, 0


def mailbox_health(mb: Mailbox) -> int:
    """0 to 100. Missing DNS records and a high bounce rate cost points. Shown on the Deliverability page."""
    score = 100 - 15 * sum(1 for ok in (mb.spf_ok, mb.dkim_ok, mb.dmarc_ok) if not ok)
    if mb.sent_total:
        score -= min(50, int(400 * mb.bounce_count / mb.sent_total))
    if mb.warmup_days < 14:
        score -= 10
    return max(0, min(100, score))


def pick_mailbox(session: Session, now: datetime, rate: float = BOUNCE_RATE_PAUSE, min_sends: int = MIN_SENDS_FOR_BOUNCE_CHECK) -> Mailbox | None:
    boxes = list(session.scalars(select(Mailbox).where(Mailbox.is_active.is_(True)).order_by(Mailbox.id)))
    best, best_ratio = None, 2.0
    for mb in boxes:
        reset_mailbox_day(mb, now)
        if maybe_pause_for_bounces(mb, rate, min_sends) or not mb.is_active:
            continue
        if mb.sent_today >= mb.daily_cap:
            continue
        ratio = mb.sent_today / max(1, mb.daily_cap)
        if ratio < best_ratio:
            best, best_ratio = mb, ratio
    return best


def bounce_limits(settings: BaseAppSettings) -> tuple[float, int]:
    """(share of bounces that pauses a mailbox, sends before the check starts): BOUNCE_PAUSE_RATE and BOUNCE_MIN_SENDS, with the old values as defaults."""
    return getattr(settings, "bounce_pause_rate", BOUNCE_RATE_PAUSE), getattr(settings, "bounce_min_sends", MIN_SENDS_FOR_BOUNCE_CHECK)


def maybe_pause_for_bounces(mb: Mailbox, rate: float = BOUNCE_RATE_PAUSE, min_sends: int = MIN_SENDS_FOR_BOUNCE_CHECK) -> bool:
    if mb.sent_total >= min_sends and mb.bounce_count / mb.sent_total > rate and mb.is_active:
        mb.is_active, mb.paused_reason = False, f"Bounce rate above {rate * 100:g} percent. Fix the list, then resume by hand."
        return True
    return False


def _stop(session: Session, enr: Enrollment, reason: str, report: TickReport, now: datetime) -> None:
    enr.status, enr.stop_reason, enr.next_send_at = "stopped", reason, None
    report.stopped += 1
    report.why(reason)
    record_event(session, "enrollment.stopped", "enrollment", enr.id, {"reason": reason})


def _ctx(lead: Lead, sender_name: str = "Alex") -> dict[str, str]:
    c = lead.contact
    return {"first_name": c.first_name, "last_name": c.last_name, "company": c.company.name if c.company else "", "industry": c.company.industry if c.company else "",
            "title": c.title, "sender_name": sender_name}


def _record_block(session: Session, lead: Lead, enr: Enrollment, channel: str, to: str, reason: str, now: datetime) -> None:
    session.add(Message(lead_id=lead.id, enrollment_id=enr.id, channel=channel, direction="out", to_addr=to, status="blocked", blocked_reason=reason, created_at=now))


def _touch(session: Session, lead: Lead, now: datetime, summary: str) -> None:
    if lead.first_touch_at is None:
        lead.first_touch_at = now
    deal = session.scalars(select(Deal).where(Deal.lead_id == lead.id)).first()
    if deal and deal.stage == "new":
        deal.stage = "contacted"
    session.add(Activity(lead_id=lead.id, kind="message", summary=summary, created_at=now))


def offline_adapter_on_real_install(settings: BaseAppSettings, channel: str) -> bool:
    """The offline `seed` adapters record a fake "sent". On a real install (DEMO_MODE=false) they must never be taken for a real send, so such a message stays a draft."""
    name = getattr(settings, "email_adapter" if channel == "email" else "sms_adapter", "")
    return (not settings.demo_mode) and name == "seed"


def deliver(
    session: Session, settings: BaseAppSettings, adapters: Any, *, lead: Lead, enr: Enrollment | None, channel: str, subject: str, body: str,
    now: datetime, respect_quiet: bool = True, report: TickReport | None = None,
) -> tuple[str, str]:
    """One send through every gate. Returns (status, reason): status is sent, drafted, deferred, blocked or stop."""
    c = lead.contact
    to = c.email if channel == "email" else c.phone
    if lead.status in STOP_STATUSES and enr is not None:
        return "stop", f"lead_{lead.status}"
    why = suppression_reason(session, email=c.email, phone=c.phone if channel == "sms" else "")
    if why:
        return "stop", why
    if channel == "email" and not is_valid_email(c.email):
        return "stop", "invalid_email"
    if "role_based" in (lead.flags or []):
        return "stop", "role_based"
    if c.company is not None and c.company.is_customer:
        return "stop", "existing_customer"
    if channel == "sms":
        if not c.sms_consent:
            return "blocked", "no_sms_consent"
        if not is_e164(c.phone):
            return "blocked", "invalid_phone"
    if respect_quiet:
        ok, reason = timing.can_send_now(now, c.timezone, settings.quiet_start_hour, settings.quiet_end_hour, settings.send_weekends)  # type: ignore[attr-defined]
        if reason == "unknown_timezone":
            return "stop", "unknown_timezone"
        if not ok:
            return "deferred", reason
    mb = None
    if channel == "email":
        mb = pick_mailbox(session, now, *bounce_limits(settings))
        if mb is None:
            return "deferred", "mailbox_caps_reached"
    body = with_footer(settings, channel, body)  # who writes, where they are, how to say stop: added here so a draft shows exactly what would go out
    msg = Message(lead_id=lead.id, enrollment_id=enr.id if enr else None, mailbox_id=mb.id if mb else None, channel=channel, direction="out",
                  to_addr=to, subject=subject, body=body, created_at=now)
    session.add(msg)
    if not would_write(settings) or offline_adapter_on_real_install(settings, channel):
        msg.status = "drafted"
        record_event(session, "message.drafted", "message", None, {"lead": lead.id, "channel": channel})
        return "drafted", ""
    # Write down that a send is about to start, and make that durable BEFORE the vendor is called. If the process dies after the vendor accepted the
    # message but before the answer is recorded, the row says "sending", and the next run counts it as unconfirmed instead of sending it again.
    msg.status = "sending"
    session.commit()
    try:
        if channel == "email":
            msg.external_id = adapters.email.send(from_addr=mb.address, to=to, subject=subject, body=body)
        else:
            msg.external_id = adapters.sms.send(to=to, text=body)
    except SafetyError:
        msg.status = "drafted"
        return "drafted", ""
    except RecipientRefused:
        return _refused(session, settings, lead, msg, mb, now)
    except SendUnconfirmed as exc:
        # The server was handed the message and then the connection broke before it answered. It may have been accepted, so it is never sent again.
        msg.status, msg.blocked_reason, msg.external_id = "unconfirmed", "send_unconfirmed" + (STEP_COUNTED if enr is not None else ""), (getattr(exc, "external_id", "") or "")[:120]  # the caller advances the step
        record_event(session, "message.unconfirmed", "message", None, {"lead": lead.id, "channel": channel})
        return "unconfirmed", "send_unconfirmed"
    except Exception as exc:  # the vendor failed, we keep the message and retry later (a limited number of times)
        counts = getattr(exc, "message_specific", True)
        msg.status, msg.blocked_reason = "failed", ("" if counts else SERVER_PROBLEM) + f"{type(exc).__name__}"[:100]
        record_event(session, "message.failed", "message", None, {"lead": lead.id, "error": type(exc).__name__})
        return "failed", type(exc).__name__
    msg.status, msg.sent_at = "sent", now
    if mb:
        mb.sent_today += 1
        mb.sent_total += 1
        maybe_pause_for_bounces(mb, *bounce_limits(settings))
    session.flush()
    record_metric(session, "messages_sent", 1, {"channel": channel})
    record_audit(session, "system", "message.sent", f"message:{msg.id}", {"lead": lead.id, "channel": channel})
    return "sent", ""


def _refused(session: Session, settings: BaseAppSettings, lead: Lead, msg: Message, mb: Mailbox | None, now: datetime) -> tuple[str, str]:
    """The mail server refused this address for good before it took the message. That is a hard bounce: the address is suppressed, the lead is dead and the
    mailbox's bounce count goes up, exactly as for a delivery report that arrives later."""
    msg.status, msg.blocked_reason = "failed", "recipient_refused"
    add_suppression(session, "email", lead.contact.email, "refused by the mail server when sending", "send")
    lead.status = "dead"
    if mb is not None:
        mb.sent_total += 1  # the attempt counts as a send, otherwise a mailbox that only ever gets refusals would show a rate of nothing
        mb.bounce_count += 1
        maybe_pause_for_bounces(mb, *bounce_limits(settings))
    record_audit(session, "system", "bounce.refused_at_send", f"lead:{lead.id}", {})
    record_event(session, "message.failed", "message", None, {"lead": lead.id, "error": "recipient_refused"})
    return "stop", "recipient_refused"


def failed_attempts(session: Session, enr: Enrollment) -> int:
    """How many times in a row the mail server refused the message of the step that is current: failed messages after the last one that was not a failure,
    not counting problems that are the mail server's own (login, certificate, connection)."""
    last_ok = session.scalar(select(func.max(Message.id)).where(Message.enrollment_id == enr.id, Message.direction == "out", Message.status != "failed")) or 0
    return int(session.scalar(select(func.count(Message.id)).where(
        Message.enrollment_id == enr.id, Message.direction == "out", Message.status == "failed", Message.id > last_ok, Message.blocked_reason.notlike(SERVER_PROBLEM + "%"))) or 0)


STALE_SENDING_MINUTES = 10


def _count_step(enr: Enrollment | None, messages: list[Message], now: datetime) -> None:
    """The step these unconfirmed messages belonged to counts as done and is NOT repeated: the vendor may or may not have sent it, and a second copy to a real
    person is worse than a missing one. The enrolment moves on once however many messages were left behind, and each message is marked so that it is never counted
    twice. A stopped enrolment does not move (it is stopped)."""
    todo = [m for m in messages if STEP_COUNTED not in m.blocked_reason]
    if not todo:
        return
    for m in todo:
        m.blocked_reason = (m.blocked_reason + STEP_COUNTED)[:120]
    if enr is not None and enr.status in {"active", "paused"}:
        _advance(enr, enr.sequence.steps, now)


def _mark_unconfirmed(session: Session, m: Message) -> None:
    m.status, m.blocked_reason = "unconfirmed", "worker_stopped_during_send"
    record_event(session, "message.unconfirmed", "message", m.id, {"lead": m.lead_id})


def sweep_stale_sends(session: Session, now: datetime) -> int:
    """A message left at "sending" for a long time belongs to a process that died. It is marked unconfirmed so nobody waits on it. Its sequence step is counted as
    done right here when the enrolment is running; for a paused one (a reply asked to wait) it is counted when the enrolment wakes, in _finish_unconfirmed_send.
    Either way nothing sends it again, however late the restart is (a killed worker keeps its job for the 30 minute lease)."""
    cutoff = aware(now) - timedelta(minutes=STALE_SENDING_MINUTES)
    stale = list(session.scalars(select(Message).where(Message.direction == "out", Message.status == "sending", Message.created_at < cutoff).order_by(Message.id)))
    by_enrollment: dict[int, list[Message]] = {}
    for m in stale:
        _mark_unconfirmed(session, m)
        if m.enrollment_id:
            by_enrollment.setdefault(m.enrollment_id, []).append(m)
    for enr_id, rows in by_enrollment.items():
        enr = session.get(Enrollment, enr_id)
        if enr is not None and enr.status == "active":
            _count_step(enr, rows, now)
    return len(stale)


def _finish_unconfirmed_send(session: Session, enr: Enrollment, steps: list, now: datetime, report: TickReport) -> bool:
    """Before this enrolment sends anything, settle every message of it that is still "sending" (the last run died less than ten minutes ago, so the sweep has not
    reached it) or "unconfirmed" and not yet counted (the enrolment was paused when the sweep ran, or the row is from an older version): the step counts as done."""
    rows = list(session.scalars(select(Message).where(Message.enrollment_id == enr.id, Message.direction == "out", or_(
        Message.status == "sending", (Message.status == "unconfirmed") & Message.blocked_reason.notlike("%" + STEP_COUNTED))).order_by(Message.id)))
    if not rows:
        return False
    for m in rows:
        if m.status == "sending":
            _mark_unconfirmed(session, m)
    report.why("send_unconfirmed")
    _count_step(enr, rows, now)
    return True


def mark_not_sent(session: Session, message_id: int, *, decided_by: str, now: datetime) -> str:
    """A person looked in the Sent folder and the message is not there: it becomes "not sent" and its step is tried again (at the next run, or when the pause
    ends). Only the newest outgoing message of an enrolment can be reopened, so a step that later messages already followed is never repeated by mistake.
    Returns "retry" (the enrolment is running), "paused" (it tries again when the pause ends) or "stopped" (the person was stopped meanwhile: nothing is sent)."""
    m = session.get(Message, message_id)
    if m is None or m.direction != "out":
        raise ValueError("That message does not exist.")
    if m.status != "unconfirmed":
        raise ValueError("Only a message that is marked unconfirmed can be marked as not sent.")
    enr = session.get(Enrollment, m.enrollment_id) if m.enrollment_id else None
    if enr is None:
        raise ValueError("This message was not part of a sequence, so there is no step to try again. Send it by hand.")
    counted = STEP_COUNTED in m.blocked_reason
    later = session.scalar(select(func.count(Message.id)).where(Message.enrollment_id == enr.id, Message.direction == "out", Message.id > m.id, Message.status.in_(("sent", "drafted", "unconfirmed", "sending")))) or 0
    if later or (counted and enr.current_step < 1):
        raise ValueError("Later steps were already sent to this person, so this one is not tried again. Send it by hand if it matters.")
    m.status, m.blocked_reason = "not_sent", f"marked not sent by {decided_by}"[:120]
    if enr.lead.status not in STOP_STATUSES:
        if counted and enr.status in {"active", "paused", "done"}:
            enr.current_step -= 1  # the step had been counted as done: it is open again
        if enr.status == "done":
            enr.status = "active"
        if enr.status == "active":
            enr.next_send_at = aware(now)
    record_audit(session, decided_by, "message.marked_not_sent", f"message:{m.id}", {"enrollment": enr.id})
    if enr.lead.status in STOP_STATUSES or enr.status not in {"active", "paused"}:
        return "stopped"
    return "retry" if enr.status == "active" else "paused"


def _advance(enr: Enrollment, steps: list, now: datetime) -> None:
    enr.current_step += 1
    if enr.current_step >= len(steps):
        enr.status, enr.next_send_at = "done", None
    else:
        enr.next_send_at = aware(now) + timedelta(hours=steps[enr.current_step].delay_hours)


def send_tick(session: Session, settings: BaseAppSettings, adapters: Any, now: datetime, batch: int = 200, refresh: Callable[[], BaseAppSettings] | None = None) -> TickReport:
    """One pass over the enrollments that are due. Every enrollment is committed on its own, so a crash or a kill part way through loses at most the one being
    sent (marked "sending", see deliver), never the ones already sent. `refresh` returns the settings as they are NOW (the kill switch can be turned on in the app
    while a batch runs); it is asked before every send."""
    report = TickReport()
    current = refresh or (lambda: settings)
    if current().kill_switch:
        report.halted = True
        return report
    if sweep_stale_sends(session, now):
        session.commit()
    due = list(session.scalars(
        select(Enrollment).where(Enrollment.status == "active", Enrollment.next_send_at.is_not(None), Enrollment.next_send_at <= now)
        .order_by(Enrollment.next_send_at, Enrollment.id).limit(batch)
    ))
    # also wake paused enrollments whose pause ended
    woken = list(session.scalars(select(Enrollment).where(Enrollment.status == "paused", Enrollment.paused_until.is_not(None), Enrollment.paused_until <= now)))
    for e in woken:
        e.status, e.paused_until, e.next_send_at = "active", None, now
        due.append(e)
    if woken:
        session.commit()
    for enr in due:
        live = current()  # Pause all and "force draft" take effect between two sends, not at the next minute
        if live.kill_switch:
            report.halted = True
            break
        session.refresh(enr)  # a reply or an unsubscribe may have stopped it since the list was read
        if enr.status != "active":
            continue
        session.refresh(enr.lead)
        _tick_enrollment(session, live, adapters, enr, now, report)
        session.commit()
    session.flush()
    return report


def _tick_enrollment(session: Session, settings: BaseAppSettings, adapters: Any, enr: Enrollment, now: datetime, report: TickReport) -> None:
    lead = enr.lead
    steps = enr.sequence.steps
    if enr.current_step >= len(steps):
        enr.status, enr.next_send_at = "done", None
        return
    if _finish_unconfirmed_send(session, enr, steps, now, report):
        return
    step = steps[enr.current_step]
    try:
        name = getattr(settings, "sender_name", "Alex")
        subject = render(step.subject, _ctx(lead, name), header=True)
        body = render(step.body, _ctx(lead, name))
    except TemplateError:
        _stop(session, enr, "template_error", report, now)
        return
    status, reason = deliver(session, settings, adapters, lead=lead, enr=enr, channel=step.channel, subject=subject, body=body, now=now, report=report)
    if status == "stop":
        _stop(session, enr, reason, report, now)
        return
    if status == "deferred":
        report.deferred += 1
        report.why(reason)
        if reason == "mailbox_caps_reached":
            enr.next_send_at = timing.next_utc_midnight(now)
        else:
            enr.next_send_at = timing.next_window(now, lead.contact.timezone, settings.quiet_start_hour, settings.quiet_end_hour, settings.send_weekends) or now + timedelta(days=1)  # type: ignore[attr-defined]
        return
    if status == "failed":
        report.why("send_failed")
        if failed_attempts(session, enr) >= MAX_SEND_ATTEMPTS:
            session.add(Activity(lead_id=lead.id, kind="message", summary=f"The mail server refused step {enr.current_step + 1} {MAX_SEND_ATTEMPTS} times. The sequence for this person is stopped: check the address and the mailbox.", created_at=now))
            _stop(session, enr, "send_failed_repeatedly", report, now)  # the server keeps refusing this message: a person decides, it is not retried for ever
            return
        enr.next_send_at = now + timedelta(hours=1)
        return
    if status == "unconfirmed":  # deliver() already marked the message as counted
        report.why("send_unconfirmed")
        session.add(Activity(lead_id=lead.id, kind="message", summary=f"Step {enr.current_step + 1} may or may not have been sent (the connection broke). It will not be sent again; check the Sent folder.", created_at=now))
        _advance(enr, steps, now)
        return
    if status == "blocked":
        _record_block(session, lead, enr, step.channel, lead.contact.phone, reason, now)
        report.blocked += 1
        report.why(reason)
    elif status == "drafted":
        report.drafted += 1
        _touch(session, lead, now, f"Draft {step.channel} step {enr.current_step + 1} (draft mode, not sent)")
    else:
        report.sent += 1
        _touch(session, lead, now, f"Sent {step.channel} step {enr.current_step + 1}")
    _advance(enr, steps, now)
