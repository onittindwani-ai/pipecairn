"""Webhooks: bounded bodies, replay protection, repeated deliveries stored once, and the one click unsubscribe link."""

import hashlib
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from conftest import DATA, make_settings
from pipecairn.api.app import create_app
from pipecairn.api.routes_webhooks import MAX_BODY, check_shared
from pipecairn.models import Lead, Meeting, Message, Suppression
from pipecairn.unsubscribe import make_token

SECRET = "whsec"


def sign(body: bytes, ts: str | None = None) -> str:
    signed = (ts.encode() + b"." + body) if ts else body
    return hmac.new(SECRET.encode(), signed, hashlib.sha256).hexdigest()


@pytest.fixture
def api(tmp_path):
    s = make_settings(tmp_path, seed_dir=str(DATA), webhook_shared_secret=SECRET, calcom_webhook_secret="calsec")
    app = create_app(s)
    return TestClient(app, base_url="http://api.test"), app.state.ctx


def add_lead(c, email="ava@acme.example.test"):
    body = json.dumps({"email": email, "first_name": "Ava", "company": "Acme", "domain": "acme.example.test", "timezone": "America/New_York"}).encode()
    r = c.post("/api/webhooks/form", content=body, headers={"x-signature": sign(body)})
    assert r.status_code == 200 and r.json()["created"] == 1


def test_a_declared_oversize_body_is_refused_before_it_is_read(api):
    c, _ = api
    r = c.post("/api/webhooks/email", content=b"x" * (MAX_BODY + 1), headers={"x-signature": "00"})
    assert r.status_code == 413  # refused on its size, not on its signature


def test_a_body_with_no_length_is_cut_off_while_it_arrives(api):
    c, _ = api
    chunks = (b"x" * 100_000 for _ in range(40))  # 4 MB sent in pieces, no Content-Length
    r = c.post("/api/webhooks/email", content=chunks, headers={"x-signature": "00"})
    assert r.status_code == 413


def test_a_bad_length_header_is_refused(api):
    c, _ = api
    assert c.post("/api/webhooks/email", content=b"{}", headers={"content-length": "abc"}).status_code in (400, 413)


def test_signature_with_timestamp_and_the_replay_window(api):
    _, ctx = api
    body, now = b'{"from":"a@b.test"}', 1_800_000_000
    check_shared(ctx, body, sign(body, str(now)), str(now), now=now + 10)  # fresh: passes
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as e:
        check_shared(ctx, body, sign(body, str(now)), str(now), now=now + 301)  # captured and replayed later
    assert e.value.status_code == 401
    with pytest.raises(HTTPException):
        check_shared(ctx, body, sign(body), str(now), now=now)  # body only signature does not satisfy a timestamped request
    with pytest.raises(HTTPException):
        check_shared(ctx, body, sign(body, "abc"), "abc", now=now)
    check_shared(ctx, body, sign(body), None)  # senders that send no timestamp still work


def test_a_timestamped_request_over_http(api):
    c, _ = api
    body = json.dumps({"email": "t@acme.example.test", "domain": "acme.example.test"}).encode()
    ts = str(int(time.time()))
    assert c.post("/api/webhooks/form", content=body, headers={"x-signature": sign(body, ts), "x-timestamp": ts}).status_code == 200
    old = str(int(time.time()) - 3600)
    assert c.post("/api/webhooks/form", content=body, headers={"x-signature": sign(body, old), "x-timestamp": old}).status_code == 401


def test_the_same_signed_email_with_no_message_id_is_stored_once(api):
    c, ctx = api
    add_lead(c)
    body = json.dumps({"from": "ava@acme.example.test", "to": "sam@x.test", "subject": "Re: hi", "text": "Yes, send a proposal please."}).encode()
    h = {"x-signature": sign(body)}
    assert c.post("/api/webhooks/email", content=body, headers=h).json()["captured"] is True
    assert c.post("/api/webhooks/email", content=body, headers=h).json()["captured"] is False  # a replay
    with ctx.factory() as s:
        assert len(list(s.scalars(select(Message).where(Message.direction == "in")))) == 1


def test_a_booking_without_an_id_is_stored_once(api):
    c, ctx = api
    add_lead(c)
    cal = json.dumps({"triggerEvent": "BOOKING_CREATED", "payload": {"attendees": [{"email": "ava@acme.example.test"}], "startTime": "2026-12-02T15:00:00Z", "endTime": "2026-12-02T15:30:00Z"}}).encode()
    h = {"x-cal-signature-256": hmac.new(b"calsec", cal, hashlib.sha256).hexdigest()}
    assert c.post("/api/webhooks/calcom", content=cal, headers=h).json().get("captured") is True
    assert c.post("/api/webhooks/calcom", content=cal, headers=h).json().get("ignored") is True
    with ctx.factory() as s:
        assert len(list(s.scalars(select(Meeting)))) == 1


def test_a_forwarded_delivery_report_needs_the_proof_fields(api):
    c, ctx = api
    add_lead(c)
    body = json.dumps({"from": "mailer-daemon@evil.example.test", "subject": "Mail delivery failed", "text": "550 5.1.1 User unknown ava@acme.example.test", "message_id": "m-1"}).encode()
    r = c.post("/api/webhooks/email", content=body, headers={"x-signature": sign(body)})
    assert r.json()["captured"] is False  # not from the lead, not a report that names a message we sent


def test_unsubscribe_link_opening_changes_nothing_and_the_post_suppresses(api):
    c, ctx = api
    add_lead(c)
    token = make_token(ctx.settings.session_secret, "ava@acme.example.test")
    page = c.get(f"/api/webhooks/unsubscribe/{token}")
    assert page.status_code == 200 and "<form" in page.text
    with ctx.factory() as s:
        assert s.scalars(select(Suppression)).first() is None  # a mail scanner opening the link changed nothing
    assert c.post(f"/api/webhooks/unsubscribe/{token}").json() == {"ok": True}
    with ctx.factory() as s:
        assert s.scalars(select(Suppression).where(Suppression.value == "ava@acme.example.test")).first() is not None
        assert s.scalars(select(Lead)).first().status == "suppressed"
    assert c.post("/api/webhooks/unsubscribe/not-a-token").status_code == 404
    assert c.get("/api/webhooks/unsubscribe/not-a-token").status_code == 404
