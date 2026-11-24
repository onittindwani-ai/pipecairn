"""Regressions found by walking every screen as a first time owner (Round 5)."""

from test_api import client, full_cycle, login  # noqa: F401  (fixture re-used)


def replies_ready(client):
    full_cycle(client)
    for _ in range(6):
        client.post("/api/demo/advance", json={"hours": 30})
        client.post("/api/demo/tick")
    return client.get("/api/inbox").json()


def test_approving_while_the_kill_switch_is_on_changes_nothing(client):
    inbox = replies_ready(client)
    reply = next(r for r in inbox if r["intent"] == "interested" and not r["handled"])
    client.post("/api/settings", json={"kill_switch": True})
    r = client.post(f"/api/inbox/{reply['id']}/approve", json={})
    assert r.status_code == 409 and "kill switch" in r.json()["error"]["message"].lower()
    again = next(x for x in client.get("/api/inbox").json() if x["id"] == reply["id"])
    assert again["handled"] is False  # the reply is still waiting for a person
    pending = [a for a in client.get("/api/approvals").json() if a["status"] == "pending"]
    assert any(a["id"] == reply["approval_id"] for a in pending)
    client.post("/api/settings", json={"kill_switch": False})
    assert client.post(f"/api/inbox/{reply['id']}/approve", json={}).status_code == 200


def test_booking_a_call_closes_the_reply_and_its_pending_draft(client):
    inbox = replies_ready(client)
    reply = next(r for r in inbox if r["intent"] == "interested" and not r["handled"])
    slot = client.get(f"/api/inbox/{reply['id']}/slots").json()[0]
    assert client.post(f"/api/inbox/{reply['id']}/book", json={"slot": slot}).status_code == 200
    after = next(x for x in client.get("/api/inbox").json() if x["id"] == reply["id"])
    assert after["handled"] is True
    assert not [a for a in client.get("/api/approvals").json() if a["id"] == reply["approval_id"] and a["status"] == "pending"]
    # a second booking for the same lead is refused instead of creating a second meeting
    assert client.post(f"/api/inbox/{reply['id']}/book", json={"slot": slot}).status_code == 409


def test_no_call_is_booked_for_someone_who_asked_to_stop(client):
    inbox = replies_ready(client)
    stop = next(r for r in inbox if r["intent"] == "unsubscribe")
    slot = client.get(f"/api/inbox/{stop['id']}/slots").json()[0]
    r = client.post(f"/api/inbox/{stop['id']}/book", json={"slot": slot})
    assert r.status_code == 409


def test_a_sequence_cannot_be_saved_with_an_empty_message_or_subject(client):
    login(client)
    client.post("/api/demo/reset")
    seq = client.get("/api/sequences").json()[0]
    steps = [{k: s[k] for k in ("channel", "delay_hours", "subject", "body")} for s in seq["steps"]]
    blank_body = [dict(steps[0], body="   ")] + steps[1:]
    r = client.put(f"/api/sequences/{seq['id']}", json={"name": seq["name"], "steps": blank_body})
    assert r.status_code == 422 and "no message" in r.json()["error"]["message"]
    blank_subject = [dict(steps[0], channel="email", subject="")] + steps[1:]  # only the first email needs one
    r = client.put(f"/api/sequences/{seq['id']}", json={"name": seq["name"], "steps": blank_subject})
    assert r.status_code == 422 and "subject" in r.json()["error"]["message"]
    assert client.put(f"/api/sequences/{seq['id']}", json={"name": seq["name"], "steps": steps}).status_code == 200


def test_overview_has_ninety_days_so_the_range_buttons_mean_something(client):
    full_cycle(client)
    daily = client.get("/api/overview").json()["daily"]
    assert len(daily) == 90 and daily[-1]["sent"] >= 0


def test_contract_open_items_say_what_they_are(client):
    full_cycle(client)
    lead = client.get("/api/leads?limit=1").json()["rows"][0]
    body = {"lead_id": lead["id"], "title": "T", "scope": ["a"], "price_cents": 1000, "call_notes": ""}
    p = client.post("/api/proposals", json=body).json()
    items = client.post(f"/api/proposals/{p['id']}/contract").json()["open_items"]
    assert any(i.startswith("Payment terms") for i in items) and any(i.startswith("Start date") for i in items)


def test_a_blank_reply_cannot_be_approved_and_stays_open(client):
    inbox = replies_ready(client)
    reply = next(r for r in inbox if r["intent"] == "wrong_person" and not r["handled"])
    for blank in ("", "   \n"):
        r = client.post(f"/api/inbox/{reply['id']}/approve", json={"body": blank})
        assert r.status_code == 409 and "empty" in r.json()["error"]["message"].lower()
    again = next(x for x in client.get("/api/inbox").json() if x["id"] == reply["id"])
    assert again["handled"] is False  # nothing was sent and the draft is still waiting
    assert client.post(f"/api/inbox/{reply['id']}/approve", json={"body": "Thanks, who is the right person?"}).status_code == 200


def test_the_lead_list_takes_several_statuses_at_once(client):
    replies_ready(client)
    one = client.get("/api/leads?limit=500&status=replied").json()["rows"]
    two = client.get("/api/leads?limit=500&status=replied,enrolled").json()["rows"]
    assert one and {r["status"] for r in one} == {"replied"}
    assert {r["status"] for r in two} == {"replied", "enrolled"} and len(two) > len(one)


def test_the_score_explanation_reads_as_words_not_a_python_dict(client):
    full_cycle(client)
    scored = [r for r in client.get("/api/leads?limit=500").json()["rows"] if r["score"] is not None][0]
    text = client.get(f"/api/leads/{scored['id']}").json()["score_explanation"]
    assert text and "{" not in text and "'" not in text and "title " in text
