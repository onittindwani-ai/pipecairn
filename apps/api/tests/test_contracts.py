"""Contract tests: the adapters against the excerpts of the vendors' public docs saved in mock/contracts/.

These excerpts were read from public docs on 2026-11-23 (see each SOURCE.txt). They are field lists and examples, not the vendors'
machine readable spec files, and nothing here ran against a real service. Twenty and the mail protocols have no such spec: see their SOURCE.txt.
"""

import base64
import json
import time
from datetime import UTC, datetime
from email import message_from_string
from pathlib import Path

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

from support import make_settings
from pipecairn.adapters.calcom import CalcomCalendar
from pipecairn.adapters.telnyx import TelnyxSms, parse_inbound, verify_telnyx_webhook
from sendora_core.adapters import AdapterError

C = Path(__file__).resolve().parents[3] / "mock" / "contracts"


def load(vendor: str, name: str) -> dict:
    return json.loads((C / vendor / name).read_text(encoding="utf-8"))


def client(handler) -> httpx.Client:
    return httpx.Client(base_url="https://api.example.test", transport=httpx.MockTransport(handler))


def test_every_contract_folder_says_where_it_came_from():
    for d in C.iterdir():
        text = (d / "SOURCE.txt").read_text(encoding="utf-8")
        assert "2026-11-23" in text and ("http" in text or "RFC" in text)


def test_calcom_slots_request_and_response_match_the_docs(tmp_path):
    doc = load("calcom", "slots.json")
    seen = {}

    def handler(req: httpx.Request):
        seen.update(path=req.url.path, params=dict(req.url.params), version=req.headers["cal-api-version"], auth=req.headers.get("authorization"))
        return httpx.Response(200, json=doc["response_example"])

    s = make_settings(tmp_path, calcom_event_type_id="10", calcom_api_key="k")
    slots = CalcomCalendar(s, client(handler)).slots(datetime(2033, 9, 5, tzinfo=UTC), datetime(2033, 9, 6, tzinfo=UTC))
    assert seen["path"] == "/v2/slots" and set(seen["params"]) == set(doc["query"])
    assert seen["version"] == doc["header"]["cal-api-version"] == s.calcom_slots_version
    assert seen["params"]["start"].endswith("Z") and seen["params"]["eventTypeId"] == "10"
    assert [d.astimezone(UTC).isoformat() for d in slots] == ["2033-09-05T07:00:00+00:00", "2033-09-05T08:00:00+00:00"]  # the +02:00 offsets are read correctly


def test_calcom_booking_request_and_response_match_the_docs(tmp_path):
    doc = load("calcom", "booking.json")
    seen = {}

    def handler(req: httpx.Request):
        seen.update(path=req.url.path, body=json.loads(req.content), version=req.headers["cal-api-version"])
        return httpx.Response(201, json=doc["response_example"])

    s = make_settings(tmp_path, calcom_event_type_id="123", calcom_api_key="k")
    b = CalcomCalendar(s, client(handler)).book(start=datetime(2024, 8, 13, 9, 0, tzinfo=UTC), name="John Doe", email="john.doe@example.com", timezone="America/New_York")
    body = seen["body"]
    assert seen["path"] == "/v2/bookings" and seen["version"] == doc["header"]["cal-api-version"] == s.calcom_bookings_version
    assert all(k in body for k in doc["request_required"]) and all(k in body["attendee"] for k in doc["attendee_required"])
    assert body["start"] == doc["request_example"]["start"] and body["attendee"] == doc["request_example"]["attendee"]
    assert body[doc["event_type_field"]] == "123" or body[doc["event_type_field"]] == 123
    assert b.external_id == "booking_uid_123"
    assert b.starts_at.isoformat() == "2024-08-13T15:30:00+00:00" and b.ends_at.isoformat() == "2024-08-13T16:30:00+00:00"


def test_telnyx_send_request_uses_only_documented_fields_and_reads_the_documented_response(tmp_path):
    doc = load("telnyx", "send_message.json")
    seen = {}

    def handler(req: httpx.Request):
        seen.update(path=req.url.path, method=req.method, body=json.loads(req.content))
        return httpx.Response(200, json=doc["response_example"])

    s = make_settings(tmp_path, telnyx_api_key="k", telnyx_from_number="+15550100124")
    out = TelnyxSms(s, client(handler)).send(to="+15550100123", text="Hello")
    assert seen["path"] == doc["path"] and seen["method"] == doc["method"]
    assert set(seen["body"]) <= set(doc["request_fields"]) and all(r in seen["body"] for r in doc["request_required"])
    assert seen["body"]["text"] == "Hello" and out == "40385f64-5717-4562-b3fc-2c963f66afa6"


def test_telnyx_error_shape_is_read_into_a_plain_message(tmp_path):
    doc = load("telnyx", "send_message.json")
    s = make_settings(tmp_path, telnyx_api_key="k", telnyx_from_number="+15550100124")
    with pytest.raises(AdapterError, match="The 'to' address is invalid"):
        TelnyxSms(s, client(lambda r: httpx.Response(400, json=doc["error_example"]))).send(to="bad", text="x")


def test_telnyx_inbound_webhook_and_signature_follow_the_documented_scheme():
    doc = load("telnyx", "inbound_webhook.json")
    sms = parse_inbound(doc["example_shape"])
    assert (sms.external_id, sms.from_number, sms.to_number, sms.text) == ("msg-1", "+15550100124", "+15550100123", "Yes please")
    key = Ed25519PrivateKey.generate()
    pub = base64.b64encode(key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
    body = json.dumps(doc["example_shape"], separators=(",", ":")).encode()
    ts = str(int(time.time()))
    sig = base64.b64encode(key.sign(ts.encode() + b"|" + body)).decode()  # timestamp, a pipe, the raw body
    assert verify_telnyx_webhook(pub, body, sig, ts)
    assert not verify_telnyx_webhook(pub, json.dumps(doc["example_shape"], indent=2).encode(), sig, ts)  # a re-serialised body fails
    old = str(int(time.time()) - doc["max_age_seconds"] - 5)
    assert not verify_telnyx_webhook(pub, body, base64.b64encode(key.sign(old.encode() + b"|" + body)).decode(), old)


def test_a_built_email_has_the_rfc_5322_header_fields(tmp_path):
    from mock.mail_servers import StubMailServers
    from pipecairn.adapters.smtp_imap import SmtpImapEmail

    with StubMailServers() as srv:
        s = make_settings(tmp_path, smtp_host=srv.host, smtp_port=srv.smtp_port, smtp_use_tls=False, smtp_user="u", smtp_password="p",
                          imap_host=srv.host, imap_port=srv.imap_port, imap_use_ssl=False)
        SmtpImapEmail(s).send(from_addr="alex@mail.example.test", to="ava@x.example.test", subject="Hi", body="Hello")
        msg = message_from_string(srv.store.outbox[0]["data"])
    assert msg["From"] == "alex@mail.example.test" and msg["To"] == "ava@x.example.test" and msg["Subject"] == "Hi"
    assert msg["Message-ID"].startswith("<") and msg["Message-ID"].endswith(">")  # RFC 5322: msg-id in angle brackets
