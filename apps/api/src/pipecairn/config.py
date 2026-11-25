"""Pipecairn settings. Subclass of the base settings with this system's variables (names only, never values, in docs)."""

from __future__ import annotations

import re

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from sendora_core.settings import BaseAppSettings, Mode

DEFAULT_SENDER_NAME = "Alex"
DEFAULT_COMPANY_NAME = "Your Company"
EMAIL_LIKE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class Settings(BaseAppSettings):
    # An empty line in .env (LLM_CALL_BUDGET=) means "not set", so a copy of .env.example loads as it is.
    model_config = SettingsConfigDict(env_ignore_empty=True)

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

    # Who the messages come from. The defaults are placeholders: problems() lists them and a live, non demo start is refused until they are real.
    sender_name: str = Field(default=DEFAULT_SENDER_NAME, max_length=80)  # SENDER_NAME: signs replies and fills {{sender_name}}
    company_name: str = Field(default=DEFAULT_COMPANY_NAME, max_length=120)  # COMPANY_NAME: the "From" company on proposals and contracts and in the footer
    company_address: str = Field(default="", max_length=300)  # COMPANY_ADDRESS: physical postal address, printed in every email footer
    reply_to: str = Field(default="", max_length=254)  # REPLY_TO: optional Reply-To address for outgoing email
    public_base_url: str = ""  # PUBLIC_BASE_URL: where this API is reachable from the internet; turns on the one click unsubscribe link in email headers
    allow_private_base_urls: bool = False  # ALLOW_PRIVATE_BASE_URLS: let CRM, calendar and texting URLs point at a private address (a self hosted Twenty or Cal.com)

    # Business rules that used to be code constants. The defaults are the old values.
    target_industries: str = "home services,dental,legal,real estate,accounting"  # TARGET_INDUSTRIES: comma separated, worth the full industry points
    min_enroll_score: int = Field(default=40, ge=0, le=100)  # MIN_ENROLL_SCORE: leads scoring below this are not enrolled
    bounce_pause_rate: float = Field(default=0.05, gt=0, le=1)  # BOUNCE_PAUSE_RATE: a mailbox above this share of bounces pauses
    bounce_min_sends: int = Field(default=20, ge=1)  # BOUNCE_MIN_SENDS: the bounce check starts after this many sends
    default_timezone: str = ""  # DEFAULT_TIMEZONE: used for a CSV row with no valid timezone (for example America/New_York). Empty means such rows are flagged and never sent to
    currency_symbol: str = Field(default="$", max_length=3)  # CURRENCY_SYMBOL: shown before prices in proposals and contracts
    proposal_valid_days: int = Field(default=14, ge=1, le=365)  # PROPOSAL_VALID_DAYS
    contract_notice_days: int = Field(default=14, ge=0, le=365)  # CONTRACT_NOTICE_DAYS: written notice to end a contract
    deal_value_small_cents: int = Field(default=150_000, ge=0)  # DEAL_VALUE_SMALL_CENTS: placeholder deal value for companies of 10 people or fewer
    deal_value_medium_cents: int = Field(default=600_000, ge=0)  # DEAL_VALUE_MEDIUM_CENTS: 11 to 200 people
    deal_value_large_cents: int = Field(default=1_200_000, ge=0)  # DEAL_VALUE_LARGE_CENTS: over 200 people
    page_size: str = Field(default="letter", pattern="^(letter|a4)$")  # PAGE_SIZE: for proposal and contract PDFs
    log_level: str = Field(default="INFO", pattern="^(DEBUG|INFO|WARNING|ERROR)$")  # LOG_LEVEL

    def industries(self) -> tuple[str, ...]:
        return tuple(x.strip().lower() for x in self.target_industries.split(",") if x.strip())

    def deal_values(self) -> tuple[int, int, int]:
        return (self.deal_value_small_cents, self.deal_value_medium_cents, self.deal_value_large_cents)

    def identity_problems(self) -> list[str]:
        """What is still a placeholder in the sender identity. A real email needs a real name, company and postal address."""
        out: list[str] = []
        if self.sender_name.strip() in {"", DEFAULT_SENDER_NAME}:
            out.append("SENDER_NAME is still the placeholder. Set the name that signs your messages.")
        if self.company_name.strip() in {"", DEFAULT_COMPANY_NAME}:
            out.append("COMPANY_NAME is still the placeholder. Set your company name.")
        if len(self.company_address.strip()) < 10:
            out.append("COMPANY_ADDRESS is empty. Commercial email needs your physical postal address in the footer.")
        if self.reply_to and not EMAIL_LIKE.match(self.reply_to):
            out.append("REPLY_TO is not an email address.")
        return out

    def runtime_errors(self) -> list[str]:
        out = super().runtime_errors()
        if self.mode is Mode.LIVE and not self.demo_mode:
            out += self.identity_problems()
        return list(dict.fromkeys(out))

    def problems(self) -> list[str]:
        out = [p for p in super().problems() if not (self.demo_mode and p.startswith("MODE is live while DEMO_MODE"))]
        if not self.demo_mode and not self.owner_password_hash:
            out.append("OWNER_PASSWORD_HASH is empty. Create one with tools/hash_password.py and set it before you run outside demo mode.")
        if self.demo_mode and self.owner_password_hash:
            out.append("DEMO_MODE is true but an owner password is set. The public demo password is switched off; set DEMO_MODE=false for a real install.")
        if not self.demo_mode:
            out += [p for p in self.identity_problems() if p not in out]
        if not self.demo_mode and self.mode.value == "live" and self.webhook_shared_secret == "":
            out.append("WEBHOOK_SHARED_SECRET is empty, so signed inbound email webhooks are refused.")
        if self.mode is Mode.LIVE and self.email_adapter == "seed" and not self.demo_mode:
            out.append("MODE is live but EMAIL_ADAPTER is seed, so nothing real can be sent. Set EMAIL_ADAPTER=smtp_imap.")
        return out
