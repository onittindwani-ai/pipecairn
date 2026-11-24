"""Pipecairn settings. Subclass of the base settings with this system's variables (names only, never values, in docs)."""

from __future__ import annotations

from pydantic import Field

from sendora_core.settings import BaseAppSettings, Mode


class Settings(BaseAppSettings):
    app_name: str = "pipecairn"
    database_url: str = "sqlite:///./pipecairn.sqlite3"

    owner_email: str = "owner@example.test"
    owner_password_hash: str | None = None  # argon2 hash, required when DEMO_MODE is false
    approver_email: str | None = None
    approver_password_hash: str | None = None
    login_burst: int = Field(default=5, ge=1, le=1000)  # sign in tries in a row before a short wait; the browser tests raise it
    viewer_email: str | None = None  # read only role: may look at everything, change nothing
    viewer_password_hash: str | None = None

    email_adapter: str = "seed"
    sms_adapter: str = "seed"
    calendar_adapter: str = "seed"
    crm_adapter: str = "seed"
    esign_adapter: str = "seed"

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True
    imap_host: str = ""
    imap_port: int = 993
    imap_use_ssl: bool = True

    telnyx_api_key: str = ""
    telnyx_public_key: str = ""
    telnyx_from_number: str = ""
    telnyx_base_url: str = "https://api.telnyx.com"

    calcom_api_key: str = ""
    calcom_event_type_id: int = 0
    calcom_webhook_secret: str = ""
    calcom_base_url: str = "https://api.cal.com"
    calcom_slots_version: str = "2024-09-04"
    calcom_bookings_version: str = "2026-02-25"

    twenty_base_url: str = ""
    twenty_api_key: str = ""

    hubspot_token: str = ""
    notion_token: str = ""
    notion_database_id: str = ""
    google_calendar_token: str = ""

    webhook_shared_secret: str = ""
    quiet_start_hour: int = Field(default=18, ge=0, le=23)  # no sends from this local hour
    quiet_end_hour: int = Field(default=8, ge=0, le=23)  # until this local hour
    send_weekends: bool = False
    handoff_dir: str = "./handoff"
    seed_dir: str = ""  # path to the data folder, set by tools and the demo

    def problems(self) -> list[str]:
        out = [p for p in super().problems() if not (self.demo_mode and p.startswith("MODE is live while DEMO_MODE"))]
        if not self.demo_mode and not self.owner_password_hash:
            out.append("OWNER_PASSWORD_HASH is empty. Create one with tools/hash_password.py and set it before you run outside demo mode.")
        if not self.demo_mode and self.mode.value == "live" and self.webhook_shared_secret == "":
            out.append("WEBHOOK_SHARED_SECRET is empty, so signed inbound email webhooks are refused.")
        if self.mode is Mode.LIVE and self.email_adapter == "seed" and not self.demo_mode:
            out.append("MODE is live but EMAIL_ADAPTER is seed, so nothing real can be sent. Set EMAIL_ADAPTER=smtp_imap.")
        return out
