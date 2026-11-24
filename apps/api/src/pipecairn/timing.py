"""Quiet hours by the contact's own time zone. Unknown zones fail closed: nothing is sent."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pipecairn.util import aware, zone


def local_time(now_utc: datetime, tz_name: str) -> datetime | None:
    z = zone(tz_name)
    return None if z is None else aware(now_utc).astimezone(z)


def can_send_now(now_utc: datetime, tz_name: str, quiet_start: int = 18, quiet_end: int = 8, weekends: bool = False) -> tuple[bool, str]:
    """Allowed from `quiet_end` local hour up to (not including) `quiet_start`, on weekdays unless weekends is True."""
    lt = local_time(now_utc, tz_name)
    if lt is None:
        return False, "unknown_timezone"
    if not weekends and lt.weekday() >= 5:
        return False, "weekend"
    if not (quiet_end <= lt.hour < quiet_start):
        return False, "quiet_hours"
    return True, ""


def next_window(now_utc: datetime, tz_name: str, quiet_start: int = 18, quiet_end: int = 8, weekends: bool = False) -> datetime | None:
    """The next UTC instant at which sending is allowed, or None when the zone is unknown."""
    if local_time(now_utc, tz_name) is None:
        return None
    t = aware(now_utc).replace(second=0, microsecond=0)
    t += timedelta(minutes=15 - t.minute % 15)
    for _ in range(15 * 4 * 24):  # fifteen days of quarter hours is always enough
        if can_send_now(t, tz_name, quiet_start, quiet_end, weekends)[0]:
            return t
        t += timedelta(minutes=15)
    return None  # pragma: no cover


def next_utc_midnight(now_utc: datetime) -> datetime:
    n = aware(now_utc)
    return (n + timedelta(days=1)).replace(hour=0, minute=5, second=0, microsecond=0)


__all__ = ["can_send_now", "local_time", "next_utc_midnight", "next_window", "UTC"]
