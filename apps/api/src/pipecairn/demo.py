"""Demo mode helpers: reset the database to the seed data, move the clock, deliver the scripted replies."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from pipecairn import clock
from pipecairn.adapters.base import InboundEmail
from pipecairn.adapters.seed import clear_inbox, push_inbound_email
from pipecairn.models import Message, State
from pipecairn.seeding import load_seed, read_seed
from pipecairn.util import aware, normalize_email


def demo_start(real_now: datetime) -> datetime:
    """The next weekday at 17:00 UTC: lunchtime in New York and morning in Los Angeles, so some contacts can be written to and some must wait."""
    t = real_now.astimezone(UTC).replace(hour=17, minute=0, second=0, microsecond=0)
    if t <= real_now:
        t += timedelta(days=1)
    while t.weekday() >= 5:
        t += timedelta(days=1)
    return t


def reset(session: Session, ctx, with_leads: bool = True) -> dict:
    """Erase every table and load the seed data. It exists only for a demo with no owner password: with a real owner it refuses, whatever route called it."""
    from sendora_core.db import Base

    if not ctx.settings.demo_shortcuts:
        raise PermissionError("The demo reset is only available in demo mode with no owner password set.")

    seed = read_seed(_data_dir(ctx))  # read the data BEFORE anything is erased: a missing folder must not leave an empty database
    engine = session.get_bind()
    session.rollback()
    session.close()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    clear_inbox(ctx.settings)
    with ctx.factory() as s:
        start = demo_start(datetime.now(UTC))
        clock.set_offset(s, (start - datetime.now(UTC)).total_seconds() / 3600)
        s.flush()
        info = load_seed(s, seed, clock.now(s, True), with_leads=with_leads)
        s.commit()
        return {"leads_imported": info["import"].created if info["import"] else 0, "clock": clock.now(s, True).isoformat()}


def _data_dir(ctx):
    from pathlib import Path

    return Path(ctx.settings.seed_dir) if ctx.settings.seed_dir else None


def deliver_scripted(session: Session, ctx, now: datetime) -> int:
    """After a lead has been written to for a while, drop the scripted reply for that lead into the seed inbox."""
    try:
        script = read_seed(_data_dir(ctx))["inbound_script"]
    except FileNotFoundError:
        return 0  # no demo data folder: there are no scripted replies to deliver
    row = session.get(State, "script_done")
    done = set(json.loads(row.value)) if row and row.value else set()
    n = 0
    for item in script:
        e = normalize_email(item["email"])
        if e in done:
            continue
        first = session.scalars(select(Message).where(Message.to_addr == e, Message.direction == "out", Message.status.in_(("sent", "drafted"))).order_by(Message.id)).first()
        if first is None or aware(first.created_at) + timedelta(hours=item["after_hours"]) > now:
            continue
        # A scripted bounce is dressed as a real delivery report that names the message we sent, so the demo still shows the bounce path.
        dsn = item.get("intent") == "bounce"
        push_inbound_email(ctx.settings, InboundEmail(external_id=f"scripted-{e}", from_addr=e, to_addr="alex@mail.pipecairn-demo.example.test", subject="Re: Quick idea", body=item["text"],
                                                      is_dsn=dsn, references=(first.external_id,) if dsn and first.external_id else ()))
        done.add(e)
        n += 1
    if n:
        from pipecairn.context import set_state

        set_state(session, "script_done", json.dumps(sorted(done)))
    return n
