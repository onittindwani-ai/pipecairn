"""Offline seed adapters. Nothing here touches a network. They are what demo mode and the tests use.

The seed inbox lives in the database (table cl_state) so the API and the worker, which are separate processes, see the same mail.
"""

from __future__ import annotations

import fcntl
import json
import uuid
from pathlib import Path
from datetime import UTC, datetime, timedelta

from pipecairn.adapters.base import Booking, HandoffResult, InboundEmail, PersonRecord
from sendora_core.safety import write_action
from sendora_core.settings import BaseAppSettings

def inbox_path(settings: BaseAppSettings) -> Path:
    return Path(getattr(settings, "handoff_dir", "./handoff")) / ".seed_inbox.json"


def _locked_update(path: Path, fn):
    """Read, change and write the inbox file under an exclusive lock, so the API and the worker can share it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        fh.seek(0)
        raw = fh.read()
        data = json.loads(raw) if raw.strip() else []
        data, out = fn(data)
        fh.seek(0)
        fh.truncate()
        fh.write(json.dumps(data))
        return out


def push_inbound_email(settings: BaseAppSettings, e: InboundEmail) -> None:
    """Used by the demo to drop a reply into the seed inbox. The reply poll job picks it up."""
    _locked_update(inbox_path(settings), lambda d: (d + [{"external_id": e.external_id, "from_addr": e.from_addr, "to_addr": e.to_addr, "subject": e.subject, "body": e.body,
                                                          "is_dsn": e.is_dsn, "references": list(e.references), "auth_results": e.auth_results}], None))


def clear_inbox(settings: BaseAppSettings) -> None:
    _locked_update(inbox_path(settings), lambda d: ([], None))


class SeedEmail:
    def __init__(self, settings: BaseAppSettings):
        self.settings = settings

    @write_action("email.send")
    def send(self, *, from_addr: str, to: str, subject: str, body: str) -> str:
        return f"seed-{uuid.uuid4().hex[:12]}"

    def fetch_replies(self) -> list[InboundEmail]:
        box = _locked_update(inbox_path(self.settings), lambda d: ([], d))
        return [InboundEmail(**{**m, "references": tuple(m.get("references", ()))}) for m in box]

    def healthcheck(self) -> tuple[bool, str]:
        return True, "Offline seed mailbox. Nothing leaves this machine."


class SeedSms:
    def __init__(self, settings: BaseAppSettings):
        self.settings = settings

    @write_action("sms.send")
    def send(self, *, to: str, text: str) -> str:
        return f"seed-sms-{uuid.uuid4().hex[:10]}"

    def healthcheck(self) -> tuple[bool, str]:
        return True, "Offline seed texting. Nothing is sent."


class SeedCalendar:
    def __init__(self, settings: BaseAppSettings):
        self.settings = settings

    def slots(self, start: datetime, end: datetime) -> list[datetime]:
        out, d = [], start.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        while d <= end and len(out) < 3:
            if d.weekday() < 5 and d >= start.replace(hour=0, minute=0, second=0, microsecond=0):
                for h in (15, 17):
                    t = d + timedelta(hours=h)
                    if t > start and len(out) < 3:
                        out.append(t)
            d += timedelta(days=1)
        return out

    @write_action("calendar.book")
    def book(self, *, start: datetime, name: str, email: str, timezone: str) -> Booking:
        return Booking(f"seed-booking-{uuid.uuid4().hex[:8]}", start, start + timedelta(minutes=30))

    def healthcheck(self) -> tuple[bool, str]:
        return True, "Offline seed calendar with fixed example times."


class SeedCrm:
    def __init__(self, settings: BaseAppSettings):
        self.settings = settings

    @write_action("crm.upsert")
    def upsert_person(self, person: PersonRecord) -> str:
        return f"seed-crm-{abs(hash(person.email)) % 10**8}"

    def healthcheck(self) -> tuple[bool, str]:
        return True, "Offline seed CRM (the database is the CRM)."


class SeedEsign:
    def __init__(self, settings: BaseAppSettings):
        self.settings = settings

    def prepare(self, *, contract_pdf: bytes, title: str, signers: list[dict], open_items: list[str] | None = None, folder_key: str = "") -> HandoffResult:
        from pipecairn.handoff import STEPS

        return HandoffResult(package_path="", instructions="Offline seed e-signature: no folder is written. Set ESIGN_ADAPTER=breezedoc_handoff to get one.\n\n" + STEPS, sent=False)

    def healthcheck(self) -> tuple[bool, str]:
        return True, "Offline seed e-signature."
