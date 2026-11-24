from datetime import UTC, datetime

import pytest

from pipecairn import templating, timing
from pipecairn.util import clean_header, is_e164, is_role_based, is_valid_email, normalize_email, zone


@pytest.mark.parametrize("e,ok", [("a.b@x.example.test", True), ("A@X.COM", True), ("no-at-sign.example.test", False), ("double@@bad.test", False), ("spaces in@bad.test", False),
                                   ("missingtld@localhost", False), ("trailing@bad.example.test.", False), ("a..b@x.com", False), ("", False)])
def test_email_validity(e, ok):
    assert is_valid_email(e) is ok


def test_role_and_phone_and_zone():
    assert is_role_based("INFO@x.example.test") and not is_role_based("ava@x.example.test")
    assert is_e164("+14155550100") and not is_e164("555-0100")
    assert zone("America/New_York") is not None and zone("Mars/Olympus") is None and zone("") is None
    assert normalize_email("  A@B.com ") == "a@b.com"


def test_clean_header_removes_newlines():
    assert "\n" not in clean_header("Hi\r\nBcc: evil@x.test")


T = datetime(2026, 12, 1, 17, 0, tzinfo=UTC)  # Tuesday


def test_quiet_hours_by_contact_zone():
    assert timing.can_send_now(T, "America/New_York")[0]  # 12:00
    assert timing.can_send_now(T, "America/Los_Angeles")[0]  # 09:00
    assert timing.can_send_now(T, "Europe/London")[0]  # 17:00, last hour before 18:00
    assert timing.can_send_now(T, "Europe/Berlin") == (False, "quiet_hours")  # 18:00
    assert timing.can_send_now(T, "Asia/Kolkata") == (False, "quiet_hours")  # 22:30
    assert timing.can_send_now(T, "Australia/Sydney") == (False, "quiet_hours")  # 04:00
    assert timing.can_send_now(T, "Mars/Olympus") == (False, "unknown_timezone")


def test_weekends_blocked_unless_allowed():
    sat = datetime(2026, 12, 5, 17, 0, tzinfo=UTC)
    assert timing.can_send_now(sat, "America/New_York") == (False, "weekend")
    assert timing.can_send_now(sat, "America/New_York", weekends=True)[0]


def test_next_window_is_allowed_and_later():
    for tz in ("Europe/Berlin", "Asia/Kolkata", "Australia/Sydney", "America/Los_Angeles"):
        w = timing.next_window(T, tz)
        assert w is not None and w >= T and timing.can_send_now(w, tz)[0]
    assert timing.next_window(T, "Mars/Olympus") is None


def test_template_single_pass_and_unknown_field():
    ctx = {"first_name": "{{company}}", "company": "Acme"}
    assert templating.render("Hi {{first_name}} at {{company}}", ctx) == "Hi {{company}} at Acme"
    with pytest.raises(templating.TemplateError):
        templating.render("Hi {{nope}}", ctx)
    assert "\n" not in templating.render("{{first_name}}", {"first_name": "A\r\nBcc: x"}, header=True)
