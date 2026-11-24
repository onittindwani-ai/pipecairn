import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from pipecairn.api.app import create_app
from pipecairn.models import Lead
from conftest import DATA, make_settings


@pytest.fixture
def client(tmp_path):
    s = make_settings(tmp_path, seed_dir=str(DATA), mode="live", webhook_shared_secret="whsec")
    app = create_app(s)
    c = TestClient(app, base_url="http://api.test")
    return c


def login(c, email="owner@example.test"):
    r = c.post("/api/auth/login", json={"email": email, "password": "demo-password-1"})
    assert r.status_code == 200, r.text
    c.headers["x-session"] = r.json()["token"]
    return r.json()


def test_sign_in_rules(client):
    assert client.get("/api/overview").status_code == 401
    assert client.post("/api/auth/login", json={"email": "owner@example.test", "password": "wrong"}).status_code == 401
    assert client.get("/health").status_code == 200  # not under /api
    assert login(client)["role"] == "owner"
    assert client.get("/api/auth/me").json()["role"] == "owner"


def test_login_rate_limit(client):
    codes = [client.post("/api/auth/login", json={"email": "owner@example.test", "password": "x"}).status_code for _ in range(7)]
    assert codes[:5] == [401] * 5 and 429 in codes[5:]


def test_every_api_route_requires_a_session_except_login_logout_and_webhooks(client):
    spec = client.get("/openapi.json").json()
    open_routes = []
    for path, ops in spec["paths"].items():
        if not path.startswith("/api/"):
            continue
        for method in ops:
            r = client.request(method.upper(), path.replace("{lead_id}", "1").replace("{reply_id}", "1").replace("{pid}", "1").replace("{cid}", "1").replace("{deal_id}", "1").replace("{seq_id}", "1")
                               .replace("{mailbox_id}", "1").replace("{approval_id}", "1").replace("{category}", "email"), json={})
            if r.status_code != 401:
                open_routes.append((method, path, r.status_code))
    assert {p for _, p, _ in open_routes} <= {"/api/auth/login", "/api/auth/logout"} | {p for p in spec["paths"] if p.startswith("/api/webhooks/")}, open_routes


def full_cycle(client, n=1):
    login(client)
    assert client.post("/api/demo/reset").status_code == 200
    out = None
    for _ in range(n):
        out = client.post("/api/demo/tick")
        assert out.status_code == 200, out.text
    return out.json()


def test_demo_end_to_end_path(client):
    full_cycle(client)
    ov = client.get("/api/overview").json()
    assert ov["sent"] > 20 and ov["scheduled"] > 0
    # move time forward until scripted replies arrive, then read them
    for _ in range(6):
        client.post("/api/demo/advance", json={"hours": 30})
        client.post("/api/demo/tick")
    inbox = client.get("/api/inbox").json()
    intents = {r["intent"] for r in inbox}
    assert {"interested", "question", "unsubscribe"} <= intents
    # an approved reply goes out only after a person approves it
    interested = next(r for r in inbox if r["intent"] == "interested" and not r["handled"])
    before = client.get("/api/overview").json()["sent"]
    r = client.post(f"/api/inbox/{interested['id']}/approve", json={})
    assert r.status_code == 200 and r.json()["status"] == "sent"
    assert client.get("/api/overview").json()["sent"] == before + 1
    # pipeline move and won
    deal = next(d for d in client.get("/api/pipeline").json()["deals"] if d["lead_id"] == interested["lead_id"])
    assert client.post(f"/api/pipeline/{deal['id']}/move", json={"stage": "won"}).json()["stage"] == "won"
    # audit chain is intact
    assert client.get("/api/audit/verify").json()["ok"] is True


def test_proposal_contract_handoff_flow(client, tmp_path):
    full_cycle(client)
    lead = client.get("/api/leads?limit=1").json()["rows"][0]
    body = {"lead_id": lead["id"], "title": "Faster replies", "scope": ["Set up", "Train"], "price_cents": 450000, "call_notes": "- slow replies"}
    assert "$4,500.00" in client.post("/api/proposals/preview", json=body).json()["body_md"]
    p = client.post("/api/proposals", json=body).json()
    pdf = client.get(f"/api/proposals/{p['id']}/pdf")
    assert pdf.headers["content-type"] == "application/pdf" and pdf.content.startswith(b"%PDF")
    c = client.post(f"/api/proposals/{p['id']}/contract").json()
    assert c["open_items"]
    h = client.post(f"/api/contracts/{c['id']}/handoff").json()
    assert h["sent"] is False and "UNVERIFIED" in h["instructions"]


def test_kill_switch_and_draft_toggle_are_one_way_safe(client):
    full_cycle(client)
    assert client.post("/api/settings", json={"kill_switch": True}).json()["kill_switch"] is True
    r = client.post("/api/demo/tick").json()
    assert r["send"]["halted"] is True
    client.post("/api/settings", json={"kill_switch": False, "force_draft": True})
    client.post("/api/demo/advance", json={"hours": 100})
    # Leads are only touched inside their own weekday sending window, so which hour of the day the
    # test runs at decides how many are due. Step the clock in six hour pieces until some are due.
    r = client.post("/api/demo/tick").json()
    for _ in range(8):
        if r["send"]["drafted"] > 0:
            break
        client.post("/api/demo/advance", json={"hours": 6})
        r = client.post("/api/demo/tick").json()
    assert r["send"]["sent"] == 0 and r["send"]["drafted"] > 0
    assert client.get("/api/settings").json()["effective_mode"] == "draft"


def test_approver_cannot_change_settings_or_reset(client):
    login(client, "approver@example.test")
    assert client.post("/api/settings", json={"kill_switch": True}).status_code == 403
    assert client.post("/api/demo/reset").status_code == 403
    assert client.get("/api/leads").status_code == 200


def test_sequence_edit_validates_fields(client):
    login(client)
    client.post("/api/demo/reset")
    q = client.get("/api/sequences").json()[0]
    bad = {"name": q["name"], "steps": [{"channel": "email", "delay_hours": 0, "subject": "Hi {{nope}}", "body": "x"}]}
    assert client.put(f"/api/sequences/{q['id']}", json=bad).status_code == 422
    good = {"name": "Two steps", "steps": [{"channel": "email", "delay_hours": 0, "subject": "Hi {{first_name}}", "body": "Body"}, {"channel": "email", "delay_hours": 24, "subject": "", "body": "More {{company}}"}]}
    assert len(client.put(f"/api/sequences/{q['id']}", json=good).json()["steps"]) == 2
    pv = client.post("/api/sequences/preview", json={"subject": "Hi {{first_name}}", "body": "{{company}}"}).json()
    assert pv["error"] is None and "{{" not in pv["subject"]


def test_csv_import_endpoint_and_errors(client):
    login(client)
    assert client.post("/api/leads/import", json={"csv": "name\nx"}).status_code == 422
    r = client.post("/api/leads/import", json={"csv": "email,first_name,company,domain,timezone\nava@new.example.test,Ava,New Co,new.example.test,America/Chicago\nava@new.example.test,Ava,New Co,new.example.test,America/Chicago\n"}).json()
    assert r["created"] == 1 and r["duplicates"] == 1
    assert client.get("/api/leads?q=new co").json()["count"] == 1


def test_form_webhook_signature_and_speed_to_lead(client):
    import hashlib, hmac

    login(client)
    client.post("/api/demo/reset")
    body = json.dumps({"email": "hot@inbound.example.test", "first_name": "Hot", "company": "Inbound Co", "domain": "inbound.example.test", "timezone": "America/New_York", "title": "Owner"}).encode()
    sig = hmac.new(b"whsec", body, hashlib.sha256).hexdigest()
    anon = TestClient(client.app, base_url="http://api.test")
    assert anon.post("/api/webhooks/form", content=body, headers={"x-signature": "bad"}).status_code == 401
    assert anon.post("/api/webhooks/form", content=body, headers={"x-signature": sig}).json()["created"] == 1
    client.post("/api/demo/tick")
    stl = client.get("/api/overview").json()["speed_to_lead"]
    assert stl["inbound_leads"] >= 1
    assert anon.post("/api/webhooks/form", content=b"x" * 1_100_000, headers={"x-signature": sig}).status_code == 413


def test_telnyx_and_calcom_webhooks(tmp_path):
    from mock.telnyx_mock import TelnyxMock
    import hashlib, hmac

    mock = TelnyxMock()
    s = make_settings(tmp_path, seed_dir=str(DATA), telnyx_public_key=mock.public_key_b64, calcom_webhook_secret="calsec")
    c = TestClient(create_app(s), base_url="http://api.test")
    body, h = mock.signed_inbound("+14155551000", "+14155550001", "STOP")
    assert c.post("/api/webhooks/telnyx", content=body, headers={**h, "telnyx-signature-ed25519": "AAAA"}).status_code == 401
    assert c.post("/api/webhooks/telnyx", content=body, headers=h).json()["ok"] is True
    cal = json.dumps({"triggerEvent": "BOOKING_CREATED", "payload": {"uid": "u1", "attendees": [{"email": "nobody@x.test"}], "startTime": "2026-12-02T15:00:00Z", "endTime": "2026-12-02T15:30:00Z"}}).encode()
    assert c.post("/api/webhooks/calcom", content=cal, headers={"x-cal-signature-256": "bad"}).status_code == 401
    good = hmac.new(b"calsec", cal, hashlib.sha256).hexdigest()
    assert c.post("/api/webhooks/calcom", content=cal, headers={"x-cal-signature-256": good}).status_code == 200


def test_demo_routes_do_not_exist_outside_demo_mode(tmp_path):
    s = make_settings(tmp_path, demo_mode=False, mode="draft", owner_password_hash="x")
    c = TestClient(create_app(s), base_url="http://api.test")
    from sendora_core.auth import make_session_token

    c.headers["x-session"] = make_session_token(s.session_secret, "o", "owner")
    assert c.post("/api/demo/reset").status_code == 404
    assert c.post("/api/auth/login", json={"email": "owner@example.test", "password": "demo-password-1"}).status_code == 401  # demo password is refused


def test_integrations_listing_never_claims_live_verified(client):
    login(client)
    d = client.get("/api/integrations").json()
    assert len(d["adapters"]) == 15 and not any(a["live_verified"] for a in d["adapters"])
    assert all(client.post(f"/api/integrations/{c}/test").json()["ok"] for c in d["categories"])


def test_bulk_suppress_stops_sending_to_those_leads(client):
    full_cycle(client)
    rows = client.get("/api/leads?status=enrolled&limit=3").json()["rows"]
    ids = [r["id"] for r in rows]
    assert client.post("/api/leads/suppress", json={"ids": ids}).json()["suppressed"] == 3
    assert {client.get(f"/api/leads/{i}").json()["status"] for i in ids} == {"suppressed"}
    client.post("/api/demo/advance", json={"hours": 100})
    client.post("/api/demo/tick")
    assert all(e["status"] == "stopped" for i in ids for e in client.get(f"/api/leads/{i}").json()["enrollments"])
    assert client.post("/api/leads/suppress", json={"ids": []}).status_code == 422


def test_viewer_reads_everything_and_changes_nothing(client):
    login(client, "viewer@example.test")
    assert client.get("/api/leads").status_code == 200
    assert client.get("/api/approvals").status_code == 200
    assert client.post("/api/settings", json={"kill_switch": True}).status_code == 403
    assert client.post("/api/approvals/1/decide", json={"approve": True}).status_code == 403
    assert client.post("/api/demo/reset").status_code == 403


def test_the_person_who_asked_cannot_decide_their_own_request(client):
    from sendora_core.approvals import request_approval

    login(client, "owner@example.test")
    client.post("/api/demo/reset")
    with client.app.state.ctx.factory() as s:
        a = request_approval(s, "settings.change", "Turn on live mode", {}, "high", "owner@example.test")
        s.commit()
        aid = a.id
    r = client.post(f"/api/approvals/{aid}/decide", json={"approve": True})
    assert r.status_code == 409 and "someone else" in r.json()["error"]["message"]
    login(client, "approver@example.test")
    assert client.post(f"/api/approvals/{aid}/decide", json={"approve": True}).status_code == 200
