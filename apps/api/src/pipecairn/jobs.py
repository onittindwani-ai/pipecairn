"""The six background jobs and the little scheduler that keeps them running."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from pipecairn import demo, inbox, intake, metrics, model_tasks
from pipecairn.adapters.base import PersonRecord
from pipecairn.context import Ctx, set_state
from pipecairn.models import Lead, Sequence, State
from pipecairn.sender import send_tick
from sendora_core.events import record_event
from sendora_core.jobs import Handler, enqueue
from sendora_core.safety import SafetyError, guard_write

INTERVALS = {"send_tick": 60, "reply_poll": 60, "enrich": 300, "score": 300, "crm_sync": 600, "report": 7 * 24 * 3600}


def active_sequence(session: Session) -> Sequence | None:
    return session.scalars(select(Sequence).where(Sequence.active.is_(True)).order_by(Sequence.id)).first()


def job_enrich(session: Session, ctx: Ctx) -> dict:
    return {"enriched": intake.enrich_pending(session, ctx.directory)}


def job_score(session: Session, ctx: Ctx) -> dict:
    n = intake.score_pending(session, ctx.llm(session), ctx.settings.industries(), ctx.settings.deal_values())
    seq = active_sequence(session)
    e = intake.enroll_pending(session, seq, ctx.now(session), ctx.settings.min_enroll_score) if seq else 0
    return {"scored": n, "enrolled": e}


def job_send_tick(session: Session, ctx: Ctx) -> dict:
    r = send_tick(session, ctx.effective(session), ctx.adapters, ctx.now(session))
    return {"sent": r.sent, "drafted": r.drafted, "deferred": r.deferred, "blocked": r.blocked, "stopped": r.stopped, "halted": r.halted, "reasons": r.reasons}


def job_reply_poll(session: Session, ctx: Ctx) -> dict:
    n = 0
    for inbound in ctx.adapters.email.fetch_replies():
        if inbox.capture_email(session, ctx.effective(session), ctx.llm(session), ctx.adapters.calendar, inbound, ctx.now(session)):
            n += 1
    return {"captured": n}


def job_crm_sync(session: Session, ctx: Ctx) -> dict:
    done = skipped = 0
    eff = ctx.effective(session)  # the kill switch and "force draft" are set in the app, so they live in the database, not in the environment
    try:
        guard_write(eff, "crm.upsert")  # the adapter only knows the environment; this is what makes the in app switch stop every write to the CRM
    except SafetyError:
        return {"synced": 0, "skipped_by_safety": 1, "mode": eff.mode.value}
    for lead in session.scalars(select(Lead).where(Lead.crm_id == "", Lead.score.is_not(None), Lead.status.notin_(("suppressed", "dead")))):
        c = lead.contact
        try:
            lead.crm_id = ctx.adapters.crm.upsert_person(PersonRecord(email=c.email, first_name=c.first_name, last_name=c.last_name, title=c.title, phone=c.phone, company=c.company.name if c.company else ""))
            done += 1
        except SafetyError:
            skipped += 1
            break  # draft mode or kill switch: nothing is written, no point trying every lead
    return {"synced": done, "skipped_by_safety": skipped, "mode": eff.mode.value}


def job_report(session: Session, ctx: Ctx) -> dict:
    ov = metrics.overview(session, ctx.now(session))
    numbers = {k: v for k, v in ov.items() if k not in ("daily", "funnel")}
    summary = model_tasks.summarise_week(ctx.llm(session), numbers, "A rule based summary: see the numbers above.")
    text = f"# Weekly report\n\nSent {ov['sent']}, drafted {ov['drafted']}, replies {ov['replies']}, positive {ov['positive_replies']}.\n\n{summary}\n"
    set_state(session, "weekly_report", text)
    return {"chars": len(text)}


JOBS = {"enrich": job_enrich, "score": job_score, "send_tick": job_send_tick, "reply_poll": job_reply_poll, "crm_sync": job_crm_sync, "report": job_report}


def make_handlers(ctx: Ctx) -> dict[str, Handler]:
    return {kind: (lambda session, payload, fn=fn: fn(session, ctx)) for kind, fn in JOBS.items()}


def schedule_due(session: Session, ctx: Ctx) -> int:
    """Queue each job when its interval has passed since the last run. One queued job per kind at most."""
    from sendora_core.db import utcnow
    from sendora_core.models import Job

    n, now = 0, utcnow()
    for kind, secs in INTERVALS.items():
        last = session.scalars(select(Job).where(Job.kind == kind).order_by(Job.id.desc())).first()
        if last is None:
            enqueue(session, kind); n += 1
        elif last.status in {"done", "failed"} and last.finished_at is not None and (now - last.finished_at.replace(tzinfo=now.tzinfo)).total_seconds() >= secs:
            enqueue(session, kind); n += 1
    return n


def run_cycle(session: Session, ctx: Ctx) -> dict:
    """Everything once, in order. The demo's Run button and the tests use this. Jobs use the same functions."""
    out = {"enrich": job_enrich(session, ctx), "score": job_score(session, ctx)}
    out["send"] = job_send_tick(session, ctx)
    if ctx.settings.demo_shortcuts:
        out["scripted_replies"] = demo.deliver_scripted(session, ctx, ctx.now(session))
    out["replies"] = job_reply_poll(session, ctx)
    out["crm"] = job_crm_sync(session, ctx)
    record_event(session, "cycle.ran", None, None, {k: v for k, v in out.items() if k != "send"})
    return out
