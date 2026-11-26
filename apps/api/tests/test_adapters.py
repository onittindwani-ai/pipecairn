import json
import time
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from pipecairn.adapters.base import PersonRecord, safe_base_url
from pipecairn.adapters.calcom import CalcomCalendar, verify_calcom_webhook
from pipecairn.adapters.crm import HubspotCrm, NotionCrm, TwentyCrm
from pipecairn.adapters.google_calendar import GoogleCalendar
from pipecairn.adapters.smtp_imap import SmtpImapEmail
from pipecairn.adapters.telnyx import TelnyxSms, parse_inbound, verify_telnyx_webhook
from pipecairn.registry import build_adapters, build_registry
from support import make_settings
from mock.calcom_mock import CalcomMock
from mock.mail_servers import StubMailServers
from mock.telnyx_mock import TelnyxMock
from mock.twenty_mock import TwentyMock
from sendora_core.adapters import AdapterError
from sendora_core.safety import DraftModeError


def test_smtp_imap_send_and_fetch_against_stub_servers(tmp_path):
    with StubMailServers() as srv:
        s = make_settings(tmp_path, smtp_host=srv.host, smtp_port=srv.smtp_port, smtp_use_tls=False, smtp_user="demo", smtp_password="demo-password",
                          imap_host=srv.host, imap_port=srv.imap_port, imap_use_ssl=False)
        a = SmtpImapEmail(s)
        mid = a.send(from_addr="alex@mail.example.test", to="ava@x.example.test", subject="Hi\r\nBcc: evil@x.test", body="Hello there")
        assert mid.startswith("<") and len(srv.store.outbox) == 1
        assert "Bcc" not in srv.store.outbox[0]["data"].split("\n\n")[0].replace("Subject: Hi Bcc: evil@x.test", "")  # no header was added
        srv.store.deliver(b"From: Ava <ava@x.example.test>\r\nTo: alex@mail.example.test\r\nSubject: Re: Hi\r\nMessage-ID: <abc@x>\r\n\r\nYes please\r\n")
        got = a.fetch_replies()
        assert [(g.from_addr, g.body.strip(), g.external_id) for g in got] == [("ava@x.example.test", "Yes please", "<abc@x>")]
        assert len(a.fetch_replies()) == 1  # reading does not mark it read: that happens after it is stored, with mark_seen
        a.mark_seen([g.uid for g in got])
        assert a.fetch_replies() == []  # marked seen
        assert a.healthcheck()[0] is True


def test_smtp_imap_errors_are_plain_and_secret_free(tmp_path):
    s = make_settings(tmp_path, smtp_host="127.0.0.1", smtp_port=1, smtp_use_tls=False, smtp_password="supersecret")
    a = SmtpImapEmail(s)
    with pytest.raises(AdapterError) as e:
        a.send(from_addr="a@b.test", to="c@d.test", subject="s", body="b")
    assert "supersecret" not in str(e.value)
    ok, detail = a.healthcheck()
    assert not ok and "supersecret" not in detail


def test_write_actions_refuse_in_draft_mode(tmp_path):
    s = make_settings(tmp_path, mode="draft")
    with pytest.raises(DraftModeError):
        SmtpImapEmail(s).send(from_addr="a@b.test", to="c@d.test", subject="s", body="b")
    with pytest.raises(DraftModeError):
        TelnyxSms(s, client=httpx.Client()).send(to="+14155550100", text="x")


def telnyx(tmp_path, **kw):
    mock = TelnyxMock()
    s = make_settings(tmp_path, telnyx_api_key="mock-telnyx-key", telnyx_from_number="+14155550001", telnyx_public_key=mock.public_key_b64, **kw)
    c = TestClient(mock.app, base_url="http://telnyx.test", headers={"Authorization": "Bearer mock-telnyx-key"})
    return mock, s, c


def test_telnyx_send_and_errors(tmp_path):
    mock, s, c = telnyx(tmp_path)
    t = TelnyxSms(s, client=c)
    assert t.send(to="+14155550100", text="hi") in mock.messages
    with pytest.raises(AdapterError, match="E.164"):
        t.send(to="555-0100", text="hi")
    bad = TelnyxSms(s, client=TestClient(mock.app, base_url="http://telnyx.test", headers={"Authorization": "Bearer wrong"}))
    with pytest.raises(AdapterError, match="rejected the API key"):
        bad.send(to="+14155550100", text="hi")
    assert t.healthcheck()[0] is True and bad.healthcheck() == (False, "Telnyx rejected the API key.")


def test_telnyx_webhook_signature_replay_and_tamper(tmp_path):
    mock, s, _ = telnyx(tmp_path)
    body, h = mock.signed_inbound("+14155550100", "+14155550001", "STOP")
    sig, ts = h["telnyx-signature-ed25519"], h["telnyx-timestamp"]
    assert verify_telnyx_webhook(s.telnyx_public_key, body, sig, ts)
    assert not verify_telnyx_webhook(s.telnyx_public_key, body + b" ", sig, ts)  # tampered
    assert not verify_telnyx_webhook(s.telnyx_public_key, body, sig, str(int(ts) + 1))  # wrong timestamp
    old = str(int(time.time()) - 3600)
    b2, h2 = mock.signed_inbound("+14155550100", "+14155550001", "hi", timestamp=int(old))
    assert not verify_telnyx_webhook(s.telnyx_public_key, b2, h2["telnyx-signature-ed25519"], old)  # replay window
    assert not verify_telnyx_webhook("", body, sig, ts) and not verify_telnyx_webhook(s.telnyx_public_key, body, "!!!", ts)
    sms = parse_inbound(json.loads(body))
    assert sms.text == "STOP" and sms.from_number == "+14155550100"


def test_calcom_slots_book_and_conflict(tmp_path):
    mock = CalcomMock()
    s = make_settings(tmp_path, calcom_api_key="mock-cal-key", calcom_event_type_id=1001)
    c = TestClient(mock.app, base_url="http://cal.test", headers={"Authorization": "Bearer mock-cal-key"})
    cal = CalcomCalendar(s, client=c)
    now = datetime(2026, 12, 1, tzinfo=UTC)
    slots = cal.slots(now, now + timedelta(days=5))
    assert slots and all(x.tzinfo for x in slots)
    b = cal.book(start=slots[0], name="Ava Alder", email="ava@x.example.test", timezone="America/New_York")
    assert b.external_id and b.ends_at > b.starts_at
    with pytest.raises(AdapterError, match="already booked"):
        cal.book(start=slots[0], name="Ben", email="b@x.example.test", timezone="UTC")
    assert cal.healthcheck()[0]


def test_calcom_webhook_signature():
    body = b'{"triggerEvent":"BOOKING_CREATED"}'
    import hashlib, hmac

    good = hmac.new(b"sek", body, hashlib.sha256).hexdigest()
    assert verify_calcom_webhook("sek", body, good) and verify_calcom_webhook("sek", body, good.upper())
    assert not verify_calcom_webhook("sek", body + b"x", good) and not verify_calcom_webhook("", body, good) and not verify_calcom_webhook("sek", body, "no-secret-provided")


def test_twenty_upsert_is_idempotent_and_reports_errors(tmp_path):
    mock = TwentyMock()
    s = make_settings(tmp_path)
    ok = TwentyCrm(s, client=TestClient(mock.app, base_url="http://tw.test", headers={"Authorization": "Bearer mock-twenty-key"}))
    p = PersonRecord(email="ava@x.example.test", first_name="Ava", last_name="Alder", title="Owner")
    a, b = ok.upsert_person(p), ok.upsert_person(p)
    assert a == b and len(mock.people) == 1 and ok.healthcheck()[0]
    bad = TwentyCrm(s, client=TestClient(mock.app, base_url="http://tw.test", headers={"Authorization": "Bearer nope"}))
    with pytest.raises(AdapterError, match="rejected the API key"):
        bad.upsert_person(p)


def recorder(status=200, payload=None):
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(status, json=payload if payload is not None else {})

    return seen, httpx.Client(base_url="https://api.example.test", transport=httpx.MockTransport(handler))


def test_tier_b_request_shapes(tmp_path):
    s = make_settings(tmp_path, notion_database_id="db1", hubspot_token="t", notion_token="t", google_calendar_token="t")
    seen, c = recorder(200, {"id": "h1"})
    assert HubspotCrm(s, c).upsert_person(PersonRecord(email="a@x.test", first_name="A", last_name="B", title="CEO", phone="+14155550100")) == "h1"
    body = json.loads(seen[0].content)
    assert seen[0].url.path == "/crm/v3/objects/contacts" and body["properties"] == {"email": "a@x.test", "firstname": "A", "lastname": "B", "jobtitle": "CEO", "phone": "+14155550100"}
    seen, c = recorder(409)
    assert HubspotCrm(s, c).upsert_person(PersonRecord(email="a@x.test")) == "exists"
    seen, c = recorder(200, {"id": "n1"})
    NotionCrm(s, c).upsert_person(PersonRecord(email="a@x.test", first_name="A", last_name="B"))
    nb = json.loads(seen[0].content)
    assert seen[0].url.path == "/v1/pages" and nb["parent"] == {"database_id": "db1"} and nb["properties"]["Name"]["title"][0]["text"]["content"].startswith("A B")
    seen, c = recorder(200, {"id": "g1"})
    g = GoogleCalendar(s, c).book(start=datetime(2026, 12, 2, 15, tzinfo=UTC), name="A", email="a@x.test", timezone="UTC")
    assert g.external_id == "g1" and seen[0].url.params["sendUpdates"] == "all" and json.loads(seen[0].content)["attendees"] == [{"email": "a@x.test"}]
    with pytest.raises(AdapterError, match="books events only"):
        GoogleCalendar(s, c).slots(datetime.now(UTC), datetime.now(UTC))


def test_missing_keys_give_plain_errors(tmp_path):
    s = make_settings(tmp_path)
    for cls in (TelnyxSms, CalcomCalendar, TwentyCrm, HubspotCrm, NotionCrm, GoogleCalendar):
        with pytest.raises(AdapterError, match="empty|must both be set"):
            cls(s)


@pytest.mark.parametrize("url", ["http://169.254.169.254/latest", "https://localhost/x", "https://127.0.0.1", "https://10.0.0.5", "ftp://x.test", "file:///etc/passwd", "https://user:pw@example.com", "http://example.com", "https://[::1]/"])
def test_ssrf_guard_refuses(url):
    with pytest.raises(AdapterError):
        safe_base_url(url)


def test_ssrf_guard_allows_local_only_when_asked():
    assert safe_base_url("http://127.0.0.1:8000/", allow_http_local=True) == "http://127.0.0.1:8000"


def test_demo_mode_builds_only_seed_adapters(tmp_path):
    ok = build_adapters(make_settings(tmp_path))
    assert type(ok.email).__name__ == "SeedEmail"
    with pytest.raises(AdapterError, match="only offline adapters"):
        build_adapters(make_settings(tmp_path, email_adapter="smtp_imap"))
    reg = build_registry(make_settings(tmp_path))
    d = reg.describe()
    assert reg.by_tier() == {"A": 10, "B": 3, "C": 2} and len(d) == 15
    assert not any(r["live_verified"] for r in d)
    with pytest.raises(AdapterError, match="recipe only"):
        reg.get("email", "sendkit")
