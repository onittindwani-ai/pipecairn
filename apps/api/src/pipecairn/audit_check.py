"""Check the audit chain without reading all of it into memory.

The base check reads every row of the log at once, which grows without end. This one walks the newest `limit` rows one batch at a time and checks that each row
links to the one before it and that its own hash is right. The first row it reads is trusted as the starting point of the walk, so an edit older than the
window is not seen: say "all" (limit 0) to walk the whole log, in batches, when that matters.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from sendora_core.audit import GENESIS, _digest
from sendora_core.models import AuditEntry

BATCH = 500
DEFAULT_LIMIT = 20_000


def verify_recent(session: Session, limit: int = DEFAULT_LIMIT) -> tuple[bool, int | None, int]:
    """(ok, first_bad_id, rows_checked) for the newest `limit` rows (0 means every row)."""
    start = 0
    if limit:
        newest = session.scalars(select(AuditEntry.id).order_by(AuditEntry.id.desc()).offset(limit - 1).limit(1)).first()
        start = newest or 0
    prev: str | None = GENESIS if not start else None
    checked, last_id = 0, start - 1
    while True:
        batch = list(session.scalars(select(AuditEntry).where(AuditEntry.id > last_id, AuditEntry.id >= start).order_by(AuditEntry.id).limit(BATCH)))
        if not batch:
            return True, None, checked
        for e in batch:
            if prev is not None and e.prev_hash != prev:
                return False, e.id, checked
            if e.entry_hash != _digest(e.prev_hash, e.actor, e.action, e.target, e.detail, e.created_at):
                return False, e.id, checked
            prev = e.entry_hash
            checked += 1
        last_id = batch[-1].id
        session.expunge_all()  # the rows already checked are not kept in memory
