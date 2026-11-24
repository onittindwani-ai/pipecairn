"""One registry of every adapter, with its tier. Demo mode can only build the offline seed adapters."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pipecairn.adapters import seed
from pipecairn.adapters.calcom import CalcomCalendar
from pipecairn.adapters.crm import HubspotCrm, NotionCrm, TwentyCrm
from pipecairn.adapters.google_calendar import GoogleCalendar
from pipecairn.adapters.smtp_imap import SmtpImapEmail
from pipecairn.adapters.telnyx import TelnyxSms
from pipecairn.handoff import BreezedocHandoff
from sendora_core.adapters import AdapterError, AdapterRegistry, AdapterSpec

CATEGORIES = ("email", "sms", "calendar", "crm", "esign")
ENV_VARS = {
    ("email", "smtp_imap"): ["SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "IMAP_HOST", "IMAP_PORT"],
    ("sms", "telnyx"): ["TELNYX_API_KEY", "TELNYX_PUBLIC_KEY", "TELNYX_FROM_NUMBER"],
    ("calendar", "calcom"): ["CALCOM_API_KEY", "CALCOM_EVENT_TYPE_ID", "CALCOM_WEBHOOK_SECRET"],
    ("calendar", "google_calendar"): ["GOOGLE_CALENDAR_TOKEN"],
    ("crm", "twenty"): ["TWENTY_BASE_URL", "TWENTY_API_KEY"],
    ("crm", "hubspot"): ["HUBSPOT_TOKEN"],
    ("crm", "notion"): ["NOTION_TOKEN", "NOTION_DATABASE_ID"],
}


def build_registry(settings, handoff_dir: Path | None = None) -> AdapterRegistry:
    reg = AdapterRegistry(settings)
    add = lambda c, n, t, f, notes="": reg.register(AdapterSpec(c, n, t, f, False, notes))  # noqa: E731
    add("email", "seed", "A", seed.SeedEmail, "Offline. Nothing leaves this machine.")
    add("email", "smtp_imap", "A", SmtpImapEmail, "Tested against a fake SMTP and IMAP server, not a real mail host.")
    add("email", "sendkit", "C", lambda s: (_ for _ in ()).throw(AdapterError("SendKit is a recipe only. See prompts/recipe-sendkit.md.")), "Recipe prompt, not built.")
    add("sms", "seed", "A", seed.SeedSms, "Offline.")
    add("sms", "telnyx", "A", TelnyxSms, "Tested against a mock written from the public docs, not the real service.")
    add("calendar", "seed", "A", seed.SeedCalendar, "Offline example times.")
    add("calendar", "calcom", "A", CalcomCalendar, "Tested against a mock written from the public docs, not the real service.")
    add("calendar", "google_calendar", "B", GoogleCalendar, "Creates events only. Not run live.")
    add("crm", "seed", "A", seed.SeedCrm, "Offline. The Pipecairn database is the CRM.")
    add("crm", "twenty", "A", TwentyCrm, "Tested against a mock. The real field names are unverified.")
    add("crm", "hubspot", "B", HubspotCrm, "From public docs. Not run live.")
    add("crm", "notion", "B", NotionCrm, "From public docs. Not run live.")
    add("esign", "seed", "A", seed.SeedEsign, "Offline.")
    add("esign", "breezedoc_handoff", "A", lambda s: BreezedocHandoff(s, handoff_dir), "Prepares a folder. Nothing is sent automatically.")
    add("esign", "documenso", "C", lambda s: (_ for _ in ()).throw(AdapterError("Documenso is a recipe only. See prompts/recipe-documenso.md.")), "Recipe prompt, not built.")
    return reg


@dataclass
class AdapterSet:
    email: object
    sms: object
    calendar: object
    crm: object
    esign: object


def build_adapters(settings, registry: AdapterRegistry | None = None, handoff_dir: Path | None = None) -> AdapterSet:
    reg = registry or build_registry(settings, handoff_dir)
    choice = {"email": settings.email_adapter, "sms": settings.sms_adapter, "calendar": settings.calendar_adapter, "crm": settings.crm_adapter, "esign": settings.esign_adapter}
    if settings.demo_mode:
        bad = {c: n for c, n in choice.items() if n not in {"seed", "breezedoc_handoff"}}
        if bad:
            raise AdapterError(f"DEMO_MODE is on, so only offline adapters can be used. Change {', '.join(f'{c.upper()}_ADAPTER' for c in bad)} or turn DEMO_MODE off.")
    return AdapterSet(**{c: reg.get(c, n) for c, n in choice.items()})
