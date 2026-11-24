from __future__ import annotations

from pipecairn.models import Deal, Lead, Message, Reply
from pipecairn.util import aware


def iso(dt) -> str | None:
    return aware(dt).isoformat() if dt else None


def lead_row(l: Lead) -> dict:
    c = l.contact
    return {"id": l.id, "name": f"{c.first_name} {c.last_name}".strip() or c.email, "email": c.email, "company": c.company.name if c.company else "", "title": c.title,
            "status": l.status, "score": l.score, "source": l.source, "flags": l.flags or [], "timezone": c.timezone, "created_at": iso(l.created_at)}


def message_row(m: Message) -> dict:
    return {"id": m.id, "channel": m.channel, "direction": m.direction, "to": m.to_addr, "subject": m.subject, "body": m.body, "status": m.status, "blocked_reason": m.blocked_reason, "at": iso(m.sent_at or m.created_at)}


def reply_row(r: Reply) -> dict:
    l, m = r.message.lead_id, r.message
    return {"id": r.id, "lead_id": r.lead_id, "channel": m.channel, "intent": r.intent, "confidence": r.confidence, "summary": r.summary, "body": m.body, "subject": m.subject,
            "suggested_action": r.suggested_action, "draft_reply": r.draft_reply, "approval_id": r.approval_id, "handled": r.handled, "return_on": r.return_on, "created_at": iso(r.created_at)}


def deal_row(d: Deal) -> dict:
    return {"id": d.id, "lead_id": d.lead_id, "stage": d.stage, "value_cents": d.value_cents, "name": f"{d.lead.contact.first_name} {d.lead.contact.last_name}".strip(),
            "company": d.lead.contact.company.name if d.lead.contact.company else "", "score": d.lead.score, "closed_at": iso(d.closed_at), "lost_reason": d.lost_reason}
