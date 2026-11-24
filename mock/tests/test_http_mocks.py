from fastapi.testclient import TestClient

from mock.calcom_mock import CalcomMock
from mock.telnyx_mock import TelnyxMock
from mock.twenty_mock import TwentyMock

AUTH = {"authorization": "Bearer mock-telnyx-key"}


def test_telnyx_send_requires_key_and_e164():
    t = TelnyxMock()
    c = TestClient(t.app)
    assert c.post("/v2/messages", json={"to": "+14155550100", "text": "hi"}).status_code == 401
    assert c.post("/v2/messages", headers=AUTH, json={"to": "555-0100", "text": "hi"}).status_code == 422
    r = c.post("/v2/messages", headers=AUTH, json={"from": "+14155550001", "to": "+14155550100", "text": "hi"})
    assert r.status_code == 200 and r.json()["data"]["to"][0]["status"] == "queued"
    assert c.get(f"/v2/messages/{r.json()['data']['id']}", headers=AUTH).status_code == 200


def test_telnyx_signed_inbound_has_headers():
    t = TelnyxMock()
    body, headers = t.signed_inbound("+14155550100", "+14155550001", "STOP")
    assert b"message.received" in body and "telnyx-signature-ed25519" in headers


def test_calcom_slots_and_booking_conflict():
    cal = CalcomMock()
    c = TestClient(cal.app)
    h = {"authorization": "Bearer mock-cal-key", "cal-api-version": "2024-09-04"}
    assert c.get("/v2/slots", params={"eventTypeId": 1001, "start": "2026-12-01", "end": "2026-12-05"}).status_code == 401
    r = c.get("/v2/slots", headers=h, params={"eventTypeId": 1001, "start": "2026-12-01", "end": "2026-12-05"})
    first = next(iter(r.json()["data"].values()))[0]["start"]
    body = {"start": first, "eventTypeId": 1001, "attendee": {"name": "Ava Alder", "email": "ava@x.example.test", "timeZone": "America/New_York"}}
    assert c.post("/v2/bookings", headers=h, json=body).status_code == 201
    assert c.post("/v2/bookings", headers=h, json=body).status_code == 409
    assert c.post("/v2/bookings", headers={"authorization": "Bearer mock-cal-key"}, json=body).status_code == 400


def test_twenty_create_and_find_person():
    tw = TwentyMock()
    c = TestClient(tw.app)
    h = {"authorization": "Bearer mock-twenty-key"}
    data = {"name": {"firstName": "Ava", "lastName": "Alder"}, "emails": {"primaryEmail": "ava@x.example.test"}}
    assert c.post("/graphql", json={"operationName": "CreatePerson", "variables": {"data": data}}).status_code == 401
    ok = c.post("/graphql", headers=h, json={"operationName": "CreatePerson", "variables": {"data": data}}).json()
    assert ok["data"]["createPerson"]["id"]
    dup = c.post("/graphql", headers=h, json={"operationName": "CreatePerson", "variables": {"data": data}}).json()
    assert "Duplicate" in dup["errors"][0]["message"]
    found = c.post("/graphql", headers=h, json={"operationName": "FindPeople", "variables": {"email": "AVA@x.example.test"}}).json()
    assert len(found["data"]["people"]["edges"]) == 1
