"""Shared test helpers. They live here, not in conftest.py, because the base package has a conftest.py of its own and two modules named conftest cannot be imported side by side."""

import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from pipecairn.adapters.seed import SeedCalendar, SeedCrm, SeedEmail, SeedEsign, SeedSms
from pipecairn.config import Settings
from pipecairn.seeding import load_seed, read_seed
from sendora_core import models as _core  # noqa: F401
from sendora_core.db import Base, make_engine, make_session_factory

DATA = Path(__file__).resolve().parents[3] / "data"
# A Tuesday, 17:00 UTC: 12:00 New York, 09:00 Los Angeles, 17:00 London, 18:00 Berlin (quiet), 22:30 Kolkata (quiet), 04:00 Sydney (quiet).
NOW = datetime(2026, 12, 1, 17, 0, tzinfo=UTC)


class Adapters:
    def __init__(self, settings):
        self.email, self.sms = SeedEmail(settings), SeedSms(settings)
        self.calendar, self.crm, self.esign = SeedCalendar(settings), SeedCrm(settings), SeedEsign(settings)


class RecordingEmail(SeedEmail):
    def __init__(self, settings):
        super().__init__(settings)
        self.sent: list[dict] = []

    def send(self, *, from_addr, to, subject, body):
        ext = super().send(from_addr=from_addr, to=to, subject=subject, body=body)
        self.sent.append({"from": from_addr, "to": to, "subject": subject, "body": body})
        return ext


def make_settings(tmp_path, **kw) -> Settings:
    base = dict(database_url=f"sqlite:///{tmp_path / 'cl.sqlite3'}", mode="live", demo_mode=True, handoff_dir=str(tmp_path / "handoff"))
    base.update(kw)
    return Settings(_env_file=None, **base)


