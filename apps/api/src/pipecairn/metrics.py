"""Numbers for the dashboard. All of them are counts read from the database, nothing is estimated by a model."""

from __future__ import annotations

from datetime import datetime, timedelta
from statistics import median

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pipecairn.models import DEAL_STAGES, Deal, Lead, Mailbox, Message, Reply
from pipecairn.sender import mailbox_health
from pipecairn.util import aware

SPEED_TARGET_MIN = 5.0
INBOUND_SOURCES = ("form", "webhook", "referral")
MAX_ROWS = 5000  # the most rows one dashboard number may read
CHART_DAYS = 90


def speed_to_lead(session: Session) -> dict:
    """Share of inbound leads (form, webhook, referral) first touched within 5 minutes of arriving, and the median minutes."""
    rows = list(session.scalars(select(Lead).where(Lead.source.in_(INBOUND_SOURCES)).order_by(Lead.id.desc()).limit(MAX_ROWS)))  # the newest ones: a page load never reads a whole history
    touched = [l for l in rows if l.first_touch_at is not None]
    mins = [(aware(l.first_touch_at) - aware(l.created_at)).total_seconds() / 60 for l in touched]
    within = sum(1 for m in mins if m <= SPEED_TARGET_MIN)
    return {
        "inbound_leads": len(rows), "touched": len(touched), "waiting": len(rows) - len(touched),
        "within_target": within, "target_minutes": SPEED_TARGET_MIN,
        "share": (within / len(touched)) if touched else 0.0, "median_minutes": round(median(mins), 1) if mins else None,
    }


def funnel(session: Session) -> list[dict]:
    counts = dict(session.execute(select(Deal.stage, func.count()).group_by(Deal.stage)).all())
    return [{"stage": s, "count": int(counts.get(s, 0))} for s in DEAL_STAGES]


def overview(session: Session, now: datetime) -> dict:
    sent = int(session.scalar(select(func.count()).select_from(Message).where(Message.direction == "out", Message.status == "sent")) or 0)
    drafted = int(session.scalar(select(func.count()).select_from(Message).where(Message.direction == "out", Message.status == "drafted")) or 0)
    replies = int(session.scalar(select(func.count()).select_from(Reply)) or 0)
    positive = int(session.scalar(select(func.count()).select_from(Reply).where(Reply.intent.in_(("interested", "question")))) or 0)
    pipeline_cents = int(session.scalar(select(func.coalesce(func.sum(Deal.value_cents), 0)).where(Deal.stage.notin_(("won", "lost")))) or 0)
    won_cents = int(session.scalar(select(func.coalesce(func.sum(Deal.value_cents), 0)).where(Deal.stage == "won")) or 0)
    day = [(now - timedelta(days=d)).date().isoformat() for d in range(CHART_DAYS - 1, -1, -1)]
    per_day = {d: 0 for d in day}
    since = aware(now) - timedelta(days=CHART_DAYS + 1)  # only the days the chart shows are read, not every message ever sent
    for m in session.scalars(select(Message).where(Message.direction == "out", Message.status.in_(("sent", "drafted")), Message.created_at >= since).limit(MAX_ROWS * 10)):
        d = aware(m.sent_at or m.created_at).date().isoformat()
        if d in per_day:
            per_day[d] += 1
    return {
        "sent": sent, "drafted": drafted, "replies": replies, "positive_replies": positive,
        "reply_rate": round(replies / sent, 3) if sent else 0.0, "pipeline_cents": pipeline_cents, "won_cents": won_cents,
        "speed_to_lead": speed_to_lead(session), "funnel": funnel(session), "daily": [{"d": d[5:], "sent": per_day[d]} for d in day],
    }


def deliverability(session: Session) -> list[dict]:
    out = []
    for mb in session.scalars(select(Mailbox).order_by(Mailbox.id)):
        out.append({
            "id": mb.id, "address": mb.address, "daily_cap": mb.daily_cap, "sent_today": mb.sent_today, "sent_total": mb.sent_total,
            "bounce_count": mb.bounce_count, "bounce_rate": round(mb.bounce_count / mb.sent_total, 3) if mb.sent_total else 0.0,
            "warmup_days": mb.warmup_days, "spf_ok": mb.spf_ok, "dkim_ok": mb.dkim_ok, "dmarc_ok": mb.dmarc_ok, "is_active": mb.is_active,
            "paused_reason": mb.paused_reason, "health": mailbox_health(mb),
        })
    return out
