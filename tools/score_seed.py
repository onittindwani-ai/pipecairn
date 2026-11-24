"""Run the planted problems through the engine and compare with data/answer_key.json. Prints one line per check.

    python tools/score_seed.py [--json]
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import _common  # noqa: F401
from pipecairn import intake
from pipecairn.adapters.seed import SeedCalendar, SeedCrm, SeedEmail, SeedEsign, SeedSms
from pipecairn.config import Settings
from pipecairn.models import Contact, Enrollment, Lead, Mailbox, Message, Sequence
from pipecairn.seeding import load_seed, read_seed
from pipecairn.sender import send_tick
from pipecairn.util import aware, normalize_email
from sendora_core import models as _core  # noqa: F401
from sendora_core.db import Base, make_engine, make_session_factory
from sqlalchemy import select

DATA = Path(__file__).resolve().parent.parent / "data"
NOW = datetime(2026, 12, 1, 17, 0, tzinfo=UTC)


class _Adapters:
    def __init__(self, s):
        self.email, self.sms, self.calendar, self.crm, self.esign = SeedEmail(s), SeedSms(s), SeedCalendar(s), SeedCrm(s), SeedEsign(s)


def run() -> dict:
    key = json.loads((DATA / "answer_key.json").read_text())
    with tempfile.TemporaryDirectory() as d:
        s = Settings(_env_file=None, database_url=f"sqlite:///{d}/x.sqlite3", mode="live", demo_mode=True, handoff_dir=d)
        engine = make_engine(s.database_url)
        Base.metadata.create_all(engine)
        with make_session_factory(engine)() as db:
            info = load_seed(db, read_seed(DATA), NOW)
            flags = lambda f: {l.contact.email for l in db.scalars(select(Lead)) if f in (l.flags or [])}  # noqa: E731
            intake.enrich_pending(db, {})
            intake.score_pending(db, None)
            by = {l.contact.email: l.score for l in db.scalars(select(Lead))}
            seq = db.scalars(select(Sequence)).first()
            # push every must-not-send lead into the sequence on purpose, so the send gates (not only intake) are tested
            forced = 0
            for e in key["must_not_send"]:
                c = db.scalars(select(Contact).where(Contact.email == e)).first()
                lead = db.scalars(select(Lead).where(Lead.contact_id == c.id)).first() if c else None
                if lead and not db.scalars(select(Enrollment).where(Enrollment.lead_id == lead.id)).first():
                    db.add(Enrollment(lead_id=lead.id, sequence_id=seq.id, status="active", next_send_at=NOW))
                    forced += 1
            intake.enroll_pending(db, seq, NOW)
            db.commit()
            ad, t = _Adapters(s), NOW
            for _ in range(12 * 8):
                send_tick(db, s, ad, t)
                db.commit()
                t += timedelta(hours=3)
            sent_to = {normalize_email(m.to_addr) for m in db.scalars(select(Message).where(Message.direction == "out", Message.status.in_(("sent", "drafted"))))}
            boxes = {m.address: m for m in db.scalars(select(Mailbox))}
            day1 = [m for m in db.scalars(select(Message).where(Message.status == "sent", Message.channel == "email")) if aware(m.sent_at).date() == NOW.date()]
            over = boxes[key["mailbox_over_cap"]]
            checks = {
                "duplicates merged": (info["import"].duplicates, key["duplicate_group_count"]),
                "role based flagged": (len(flags("role_based") & set(key["role_based"])), len(key["role_based"])),
                "invalid emails flagged": (len(flags("invalid_email") & set(key["invalid_email"])), len(key["invalid_email"])),
                "invalid time zones flagged": (len(flags("invalid_timezone") & set(key["invalid_timezone"])), len(key["invalid_timezone"])),
                "invalid SMS phones flagged": (len(flags("invalid_phone") & set(key["invalid_sms_phone"])), len(key["invalid_sms_phone"])),
                "customer leads flagged": (len(flags("existing_customer") & set(key["customer_leads"])), len(key["customer_leads"])),
                "perfect fit leads score 70 or more": (sum(1 for e in key["perfect_fit"] if by[e] >= key["perfect_fit_min_score"]), len(key["perfect_fit"])),
                "poor fit leads score 30 or less": (sum(1 for e in key["poor_fit"] if by[e] <= key["poor_fit_max_score"]), len(key["poor_fit"])),
                "must not send addresses never written to": (len(key["must_not_send"]) - len(sent_to & set(key["must_not_send"])), len(key["must_not_send"])),
                "full mailbox sent nothing on day one": (1 if not any(m.mailbox_id == over.id for m in day1) else 0, 1),
                "bouncing mailbox was paused": (1 if not boxes[key["mailbox_high_bounce"]].is_active else 0, 1),
            }
            return {"checks": checks, "forced_into_sequence": forced, "messages_written": len(sent_to)}


def main(argv: list[str]) -> int:
    r = run()
    ok = True
    for name, (got, want) in r["checks"].items():
        good = got == want
        ok &= good
        print(("PASS " if good else "FAIL ") + f"{name}: {got} of {want}")
    print(f"({r['forced_into_sequence']} must-not-send leads were forced into the sequence to test the send gates; {r['messages_written']} addresses were written to)")
    if "--json" in argv:
        print(json.dumps(r))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
