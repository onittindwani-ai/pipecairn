"""Google Calendar (tier B, UNVERIFIED live): creates an event. It does not read availability, so offer times from your own calendar rules."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx

from pipecairn.adapters.base import Booking
from sendora_core.adapters import AdapterError
from sendora_core.safety import write_action


class GoogleCalendar:
    def __init__(self, settings, client: httpx.Client | None = None):
        self.settings = settings
        if client is not None:
            self.client = client
        else:
            if not settings.google_calendar_token:
                raise AdapterError("GOOGLE_CALENDAR_TOKEN is empty (an OAuth access token with the calendar.events scope).")
            self.client = httpx.Client(base_url="https://www.googleapis.com", timeout=15, headers={"Authorization": f"Bearer {settings.google_calendar_token}"})

    def slots(self, start: datetime, end: datetime) -> list[datetime]:
        raise AdapterError("The Google Calendar adapter books events only. Use Cal.com or add your own availability rule to offer times.")

    @write_action("calendar.book")
    def book(self, *, start: datetime, name: str, email: str, timezone: str) -> Booking:
        s, e = start.astimezone(UTC), start.astimezone(UTC) + timedelta(minutes=30)
        body = {"summary": f"Call with {name}", "start": {"dateTime": s.isoformat(), "timeZone": "UTC"}, "end": {"dateTime": e.isoformat(), "timeZone": "UTC"}, "attendees": [{"email": email}]}
        r = self.client.post("/calendar/v3/calendars/primary/events", params={"sendUpdates": "all"}, json=body)
        if r.status_code == 401:
            raise AdapterError("Google rejected the token. Access tokens expire after about an hour.")
        if r.status_code >= 400:
            raise AdapterError(f"Google Calendar refused the event: {r.status_code}")
        return Booking(str(r.json()["id"]), s, e)

    def healthcheck(self) -> tuple[bool, str]:
        try:
            r = self.client.get("/calendar/v3/calendars/primary")
        except httpx.HTTPError as exc:
            return False, f"Could not reach Google: {type(exc).__name__}."
        return (r.status_code == 200, "Google Calendar answered." if r.status_code == 200 else f"Google answered {r.status_code}.")
