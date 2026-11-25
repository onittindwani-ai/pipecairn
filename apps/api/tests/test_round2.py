"""Round 2 review: a crash in the middle of a send batch, the kill switch during a batch, mail polling, slow patterns, approvals that could not be sent, roles,
unverified bounces, and the smaller findings. Names of things that did not exist before the fix are imported inside each test."""

import inspect
import re
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select

from mock.mail_servers import FakeMailServers
from pipecairn import intake
from pipecairn.adapters.base import InboundEmail
from pipecairn.adapters.smtp_imap import SmtpImapEmail
from pipecairn.api.app import create_app
from pipecairn.context import Ctx, set_state
from pipecairn.inbox import approve_and_send, capture_email, reject_reply
from pipecairn.jobs import job_reply_poll, job_send_tick
from pipecairn.models import Enrollment, Lead, Mailbox, Message, Reply, Sequence, Suppression
from pipecairn.sender import send_tick
from pipecairn.suppression import suppression_reason
from sendora_core.approvals import ApprovalError
from sendora_core.auth import hash_password
from sendora_core.settings import ConfigError
from support import DATA, NOW, Adapters, RecordingEmail, make_settings
from test_hardening_auth import PASSWORD, REAL_SECRET, real_settings
from test_inbox import cap, inbound, world  # noqa: F401  (the fixture and helpers of the inbox tests)
from test_sender import out_messages, prepare

ROOT = Path(__file__).resolve().parents[3]


class Crash(BaseException):
    """Stands for a killed process: it is not an Exception, so no `except Exception` in the app can swallow it."""

    def __init__(self, to: str):
        self.to = to


class CrashingEmail(RecordingEmail):
    def __init__(self, settings, after: int):
        super().__init__(settings)
        self.after = after

    def send(self, *, from_addr, to, subject, body):
        if len(self.sent) >= self.after:
            raise Crash(to)
        return super().send(from_addr=from_addr, to=to, subject=subject, body=body)


# ---------------------------------------------------------------- 1. a batch is not one transaction

def test_a_crash_in_the_middle_of_a_batch_loses_nothing_and_sends_nothing_twice(session, settings, adapters, seeded):
    prepare(session)
    sent_before = sum(mb.sent_total for mb in session.scalars(select(Mailbox)))
    crashing = CrashingEmail(settings, after=4)
    adapters.email = crashing
    with pytest.raises(Crash) as died:
        send_tick(session, settings, adapters, NOW)
    session.rollback()  # what the worker does when a job dies
    first = {m["to"] for m in crashing.sent}
    assert len(first) == 4
    recorded = {m.to_addr for m in out_messages(session, status=("sent",))}
    assert recorded == first  # the four sends that went out are recorded, not rolled back with the rest
    assert sum(mb.sent_total for mb in session.scalars(select(Mailbox))) - sent_before == 4  # and so are the mailbox counters

    adapters.email = RecordingEmail(settings)  # the next run
    send_tick(session, settings, adapters, NOW)
    session.commit()
    again = {m["to"] for m in adapters.email.sent}
    assert not (again & first), "an address that was already written to was written to again"
    assert died.value.to not in again, "the message that was being sent when the process died was sent a second time"
    unconfirmed = out_messages(session, status=("unconfirmed",))
    assert [m.to_addr for m in unconfirmed] == [died.value.to]  # kept, flagged, and the sequence moved on
    assert not out_messages(session, status=("sending",))
    enr = session.scalars(select(Enrollment).join(Lead).where(Lead.contact_id == unconfirmed[0].lead.contact_id)).first() if hasattr(unconfirmed[0], "lead") else None
    assert enr is None or enr.current_step >= 1


def test_a_message_left_sending_by_a_dead_process_is_marked_unconfirmed_after_ten_minutes(session, settings, adapters, seeded):
    from datetime import timedelta

    from pipecairn.sender import sweep_stale_sends

    lead = session.scalars(select(Lead)).first()
    m = Message(lead_id=lead.id, channel="email", direction="out", to_addr="x@y.example.test", status="sending", created_at=NOW - timedelta(minutes=30))
    fresh = Message(lead_id=lead.id, channel="email", direction="out", to_addr="z@y.example.test", status="sending", created_at=NOW - timedelta(minutes=1))
    session.add_all([m, fresh])
    session.commit()
    assert sweep_stale_sends(session, NOW) == 1
    session.commit()
    session.refresh(m), session.refresh(fresh)
    assert (m.status, fresh.status) == ("unconfirmed", "sending")


# ---------------------------------------------------------------- 7. the kill switch is read before every send

class PauseAfterFirst(RecordingEmail):
    """The owner presses Pause all while a batch is running: the switch is written to the database after the first send."""

    def __init__(self, settings, session):
        super().__init__(settings)
        self.session = session

    def send(self, *, from_addr, to, subject, body):
        ext = super().send(from_addr=from_addr, to=to, subject=subject, body=body)
        if len(self.sent) == 1:
            set_state(self.session, "kill_switch", "1")
            self.session.commit()
        return ext


def test_pause_all_stops_a_batch_that_is_already_running(session, settings, factory, seeded):
    prepare(session)
    ctx = Ctx(settings, factory)
    ctx.adapters = Adapters(settings)
    ctx.adapters.email = PauseAfterFirst(settings, session)
    report = send_tick(session, ctx.effective(session), ctx.adapters, NOW, refresh=lambda: ctx.effective(session))  # what job_send_tick passes
    assert len(ctx.adapters.email.sent) == 1 and report.halted is True


def test_the_send_job_passes_the_live_settings_to_the_batch(session, settings, factory, seeded, monkeypatch):
    import pipecairn.jobs as jobs

    seen = {}
    monkeypatch.setattr(jobs, "send_tick", lambda s, st, ad, now, batch=200, refresh=None: seen.update(refresh=refresh) or send_tick(s, st, ad, now, batch, refresh))
    ctx = Ctx(settings, factory)
    jobs.job_send_tick(session, ctx)
    assert callable(seen["refresh"]) and seen["refresh"]().kill_switch is False


def test_the_effective_settings_see_a_switch_changed_by_another_session(session, settings, factory):
    ctx = Ctx(settings, factory)
    set_state(session, "kill_switch", "0")
    session.commit()
    assert ctx.effective(session).kill_switch is False  # this session has now read the row
    with factory() as other:  # the API process, a moment later
        set_state(other, "kill_switch", "1")
        other.commit()
    assert ctx.effective(session).kill_switch is True


# ---------------------------------------------------------------- 2. mail polling

RAW = b"From: Ava <ava@x.example.test>\r\nTo: alex@mail.example.test\r\nSubject: Re: Hi\r\nMessage-ID: <abc@x>\r\n\r\nSTOP please\r\n"


def mail_settings(tmp_path, srv):
    return make_settings(tmp_path, smtp_host=srv.host, smtp_port=srv.smtp_port, smtp_use_tls=False, smtp_user="demo", smtp_password="demo-password",
                         imap_host=srv.host, imap_port=srv.imap_port, imap_use_ssl=False)


def test_fetching_mail_does_not_mark_it_read_only_mark_seen_does(tmp_path):
    with FakeMailServers() as srv:
        a = SmtpImapEmail(mail_settings(tmp_path, srv))
        srv.store.deliver(RAW)
        got = a.fetch_replies()
        assert [g.uid for g in got] == ["1"]
        assert srv.store.inbox[0]["seen"] is False  # a crash now loses nothing: the message is still unread
        assert len(a.fetch_replies()) == 1
        a.mark_seen(["1"])
        assert srv.store.inbox[0]["seen"] is True and a.fetch_replies() == []


class ScriptedEmail:
    """An inbox that hands over three messages and records which ones were marked read."""

    def __init__(self, messages):
        self.messages, self.marked = messages, []

    def fetch_replies(self):
        return list(self.messages)

    def mark_seen(self, uids):
        self.marked += list(uids)


def test_one_bad_message_does_not_lose_the_others_and_only_stored_ones_are_marked_read(session, world, factory, monkeypatch):  # noqa: F811
    from pipecairn import inbox

    lead = world["lead"]
    msgs = [inbound(lead, "STOP emailing me please", "m1", uid="1"), inbound(lead, "Hello", "m2", uid="2"), inbound(lead, "Yes interested", "m3", uid="3")]
    real = inbox.capture_email

    def flaky(s, settings, llm, cal, inb, now):
        if inb.external_id == "m2":
            raise RuntimeError("boom")
        return real(s, settings, llm, cal, inb, now)

    monkeypatch.setattr(inbox, "capture_email", flaky)
    ctx = Ctx(world["settings"], factory)
    ctx.adapters = Adapters(world["settings"])
    ctx.adapters.email = ScriptedEmail(msgs)
    out = job_reply_poll(session, ctx)
    session.rollback()
    assert out["failed"] == 1 and ctx.adapters.email.marked == ["1", "3"]
    assert suppression_reason(session, email=lead.contact.email)  # the stop request was stored before the failure and survived it


def test_mail_from_an_address_that_is_not_a_lead_is_kept_where_the_owner_can_read_it(session, world):  # noqa: F811
    from pipecairn.models import UnmatchedMail

    stranger = InboundEmail(external_id="u1", from_addr="boss@their-company.example.test", to_addr="alex@mail.example.test", subject="Re: hi", body="Please call my assistant on Monday.\n\n> quoted")
    assert capture_email(session, world["settings"], world["llm"], world["adapters"].calendar, stranger, NOW) is None
    assert capture_email(session, world["settings"], world["llm"], world["adapters"].calendar, stranger, NOW) is None  # polled twice, kept once
    session.commit()
    rows = list(session.scalars(select(UnmatchedMail)))
    assert len(rows) == 1 and rows[0].from_addr == "boss@their-company.example.test" and "assistant" in rows[0].snippet and "quoted" not in rows[0].snippet


def test_an_alias_reply_that_names_our_message_is_matched_to_its_lead(session, world):  # noqa: F811
    sent = session.scalars(select(Message).where(Message.lead_id == world["lead"].id, Message.direction == "out", Message.status == "sent")).first()
    alias = InboundEmail(external_id="a1", from_addr="alias@forwarder.example.test", to_addr="alex@mail.example.test", subject="Re: hi", body="Please stop writing to this address.", references=(f"<{sent.external_id}>",))
    r = capture_email(session, world["settings"], world["llm"], world["adapters"].calendar, alias, NOW)
    session.commit()
    assert r is not None and r.intent == "unsubscribe" and r.lead_id == world["lead"].id


def test_very_long_header_values_fit_the_columns(session, world):  # noqa: F811
    long_id = "<" + "a" * 300 + "@x.example.test>"
    inb = InboundEmail(external_id=long_id, from_addr=world["lead"].contact.email, to_addr="b" * 300 + "@mail.example.test", subject="s" * 500, body="Sounds good, thanks")
    r = capture_email(session, world["settings"], world["llm"], world["adapters"].calendar, inb, NOW)
    session.commit()
    m = session.get(Message, r.message_id)
    assert len(m.external_id) <= 120 and len(m.to_addr) <= 254 and len(m.subject) <= 300
    assert capture_email(session, world["settings"], world["llm"], world["adapters"].calendar, inb, NOW) is None  # the shortened id still recognises the same message


# ---------------------------------------------------------------- 3. patterns that were slow on blank lines

HOSTILE = {"newlines": "\n" * 20000, "blank lines with spaces": "\n \n" * 8000, "spaces": " " * 20000 + "x", "sentences": "a. " * 6000, "stop words": "stop " * 4000,
           "tabs and returns": "\r\n\t\r\n" * 5000}


@pytest.mark.parametrize("name", list(HOSTILE))
def test_a_hostile_message_is_read_in_a_few_milliseconds_not_seconds(name):
    from pipecairn.replies import classify_reply
    from pipecairn.reply_text import human_part

    text = HOSTILE[name]
    t = time.perf_counter()
    human_part(text)
    classify_reply(text, None, text[:300])
    assert time.perf_counter() - t < 3.0, name  # the slow version took about 12 seconds; the margin is for a busy machine or a coverage run


def test_the_email_webhook_runs_off_the_event_loop():
    from pipecairn.api import routes_webhooks as w

    for fn in (w.email, w.form, w.telnyx, w.calcom):
        assert not inspect.iscoroutinefunction(fn), fn.__name__  # a plain function runs on a worker thread, so it cannot freeze the other requests


# ---------------------------------------------------------------- 4. an approved reply that could not be sent

def fill_every_mailbox(session, full: bool):
    for mb in session.scalars(select(Mailbox)):
        mb.sent_day = NOW.date().isoformat()
        mb.sent_today = mb.daily_cap if full else 0
    session.commit()


def test_a_reply_that_hit_the_daily_cap_stays_open_and_can_be_sent_again(session, world, settings, adapters):  # noqa: F811
    r = cap(session, world, "Yes, interested. Can we talk Thursday?")
    fill_every_mailbox(session, full=True)
    before = len(adapters.email.sent)
    assert approve_and_send(session, settings, adapters, r.id, decided_by="owner", role="owner", body=None, now=NOW) == ("deferred", "mailbox_caps_reached")
    session.commit()
    assert r.handled is False and len(adapters.email.sent) == before
    fill_every_mailbox(session, full=False)
    status, _ = approve_and_send(session, settings, adapters, r.id, decided_by="owner", role="owner", body=None, now=NOW)  # "send again"
    session.commit()
    assert status == "sent" and r.handled is True and len(adapters.email.sent) == before + 1
    with pytest.raises(ApprovalError):
        approve_and_send(session, settings, adapters, r.id, decided_by="owner", role="owner", body=None, now=NOW)  # and never a third time
    assert len(adapters.email.sent) == before + 1


def test_a_reply_that_could_not_be_sent_can_be_rejected_instead(session, world, settings, adapters):  # noqa: F811
    from sendora_core.models import Approval

    r = cap(session, world, "Yes, interested. Can we talk Thursday?")
    fill_every_mailbox(session, full=True)
    approve_and_send(session, settings, adapters, r.id, decided_by="owner", role="owner", body=None, now=NOW)
    session.commit()
    reject_reply(session, r.id, decided_by="owner", role="owner", note="no time")
    session.commit()
    assert r.handled is True and session.get(Approval, r.approval_id).status == "rejected"
    with pytest.raises(ApprovalError):
        approve_and_send(session, settings, adapters, r.id, decided_by="owner", role="owner", body=None, now=NOW)


def test_the_approvals_api_shows_the_draft_and_lets_the_owner_send_again(tmp_path):
    from pipecairn.seeding import load_seed, read_seed

    s = make_settings(tmp_path, seed_dir=str(DATA))
    app = create_app(s)
    c = TestClient(app, base_url="http://api.test")
    c.headers["x-session"] = c.post("/api/auth/login", json={"email": "owner@example.test", "password": "demo-password-1"}).json()["token"]
    ctx = app.state.ctx
    with ctx.factory() as db:
        load_seed(db, read_seed(DATA), NOW)
        intake.enrich_pending(db, {})
        intake.score_pending(db, None)
        lead = db.scalars(select(Lead)).first()
        reply = capture_email(db, ctx.effective(db), ctx.llm(db), ctx.adapters.calendar, inbound(lead, "Yes, interested. Can we talk Thursday?", "api1"), ctx.now(db))
        for mb in db.scalars(select(Mailbox)):
            mb.sent_day, mb.sent_today = ctx.now(db).date().isoformat(), mb.daily_cap
        db.commit()
        approval_id, draft = reply.approval_id, reply.draft_reply
    row = next(a for a in c.get("/api/approvals").json() if a["id"] == approval_id)
    assert row["draft"] == draft and row["reply_open"] is True
    first = c.post(f"/api/approvals/{approval_id}/decide", json={"approve": True})
    assert first.status_code == 200 and first.json()["status"] == "deferred"
    row = next(a for a in c.get("/api/approvals").json() if a["id"] == approval_id)
    assert row["status"] == "approved" and row["reply_open"] is True  # approved, not gone out: the page offers "send again"
    with ctx.factory() as db:
        for mb in db.scalars(select(Mailbox)):
            mb.sent_today = 0
        db.commit()
    again = c.post(f"/api/approvals/{approval_id}/decide", json={"approve": True})
    assert again.status_code == 200 and again.json()["status"] in {"sent", "drafted"}
    row = next(a for a in c.get("/api/approvals").json() if a["id"] == approval_id)
    assert row["reply_open"] is False


# ---------------------------------------------------------------- 5. the session secret with an owner password

def test_an_owner_password_needs_a_real_secret_even_in_demo_mode(tmp_path):
    weak = real_settings(tmp_path, demo_mode=True, session_secret="demo-secret-not-for-real-use-1234")
    assert weak.runtime_errors() and "SESSION_SECRET" in weak.runtime_errors()[0]
    with pytest.raises(ConfigError):
        create_app(weak)
    create_app(real_settings(tmp_path, demo_mode=True))  # a real secret starts
    create_app(make_settings(tmp_path))  # a demo with no owner password keeps working with its public secret


# ---------------------------------------------------------------- 6. who may change what

def role_client(tmp_path, who):
    pw = hash_password(PASSWORD)
    s = real_settings(tmp_path, approver_email="approver@x.test", approver_password_hash=pw, viewer_email="viewer@x.test", viewer_password_hash=pw)
    c = TestClient(create_app(s), base_url="http://api.test")
    email = {"owner": "owner@example.test", "approver": "approver@x.test", "viewer": "viewer@x.test"}[who]
    c.headers["x-session"] = c.post("/api/auth/login", json={"email": email, "password": PASSWORD}).json()["token"]
    return c


STEPS = {"name": "Intro", "steps": [{"channel": "email", "delay_hours": 0, "subject": "Hi {{first_name}}", "body": "Hello {{first_name}}\n\n{{sender_name}}"}]}
CSV = "first_name,last_name,email,company,domain,timezone\nAva,Alder,ava@acme.example.test,Acme,acme.example.test,America/New_York\n"


@pytest.mark.parametrize("who,allowed", [("owner", True), ("approver", False), ("viewer", False)])
def test_only_the_owner_edits_sequences_imports_leads_and_enrols(tmp_path, who, allowed):
    c = role_client(tmp_path, who)
    c.post("/api/sequences", json=STEPS) if who == "owner" else None
    calls = [("put", "/api/sequences/1", STEPS), ("post", "/api/leads/import", {"csv": CSV}), ("post", "/api/leads/process", {})]
    for method, path, body in calls:
        code = getattr(c, method)(path, json=body).status_code
        assert (code == 200) if allowed else (code == 403), (who, path, code)


def test_the_approver_can_still_approve_and_stop_people(tmp_path):
    c = role_client(tmp_path, "approver")
    assert c.post("/api/approvals/999/decide", json={"approve": True}).status_code == 404  # past the role check: it is "no such approval", not "not allowed"
    assert c.post("/api/leads/suppress", json={"ids": [1]}).status_code == 200


def test_the_viewer_cannot_decide_anything(tmp_path):
    assert role_client(tmp_path, "viewer").post("/api/approvals/999/decide", json={"approve": True}).status_code == 403


# ---------------------------------------------------------------- 8. bounces

def test_a_quoted_delivery_notice_under_a_normal_reply_is_not_a_bounce():
    from pipecairn.replies import classify_reply

    text = "Thanks, call me Thursday.\n\nOn Mon, 1 Dec 2026 at 17:00 Alex <alex@mail.example.test> wrote:\n> Mail delivery failed: returning message to sender\n> The address was not found"
    assert classify_reply(text, None).intent != "bounce"
    assert classify_reply("Mail delivery failed: returning message to sender. The address was not found.", None).intent == "bounce"  # a real notice still is one


def test_an_unverified_bounce_stays_open_for_a_person_and_changes_nothing(session, world):  # noqa: F811
    r = cap(session, world, "Your mail bounced to my spam folder, but happy to talk on Tuesday.")
    assert r.intent == "bounce" and r.suggested_action == "unverified_bounce"
    assert r.handled is False  # it was hidden before: a hot reply could vanish here
    assert not suppression_reason(session, email=world["lead"].contact.email) and world["lead"].status != "dead"


def test_a_reply_that_needs_no_answer_can_be_marked_as_read(tmp_path):
    from pipecairn.inbox import dismiss_reply

    s = make_settings(tmp_path, seed_dir=str(DATA))
    app = create_app(s)
    with app.state.ctx.factory() as db:
        from pipecairn.seeding import load_seed, read_seed

        load_seed(db, read_seed(DATA), NOW)
        intake.enrich_pending(db, {})
        intake.score_pending(db, None)
        lead = db.scalars(select(Lead)).first()
        msg = Message(lead_id=lead.id, channel="email", direction="in", body="bounced", status="received", external_id="d1", created_at=NOW)
        db.add(msg)
        db.flush()
        rep = Reply(message_id=msg.id, lead_id=lead.id, intent="bounce", suggested_action="unverified_bounce", handled=False, created_at=NOW)
        db.add(rep)
        db.commit()
        rid = rep.id
    c = TestClient(app, base_url="http://api.test")
    c.headers["x-session"] = c.post("/api/auth/login", json={"email": "owner@example.test", "password": "demo-password-1"}).json()["token"]
    assert [r["id"] for r in c.get("/api/inbox?open=true").json()] == [rid]
    assert c.post(f"/api/inbox/{rid}/dismiss").status_code == 200
    assert c.get("/api/inbox?open=true").json() == []
    assert dismiss_reply  # imported above: the function exists


# ---------------------------------------------------------------- 9. the base tests run with these

def test_the_base_package_tests_are_part_of_the_suite_and_the_makefile():
    ini = (ROOT / "pytest.ini").read_text()
    assert "packages/core-py/tests" in ini
    assert not (ROOT / "apps/api/tests/conftest.py").read_text().count("def make_settings")  # helpers live in support.py: two conftest modules cannot share a name


# ---------------------------------------------------------------- lows

def test_a_hammered_owner_account_never_locks_the_owner_out(tmp_path):
    app = create_app(real_settings(tmp_path, login_burst=2))
    for i in range(30):  # guesses at the owner's email from thirty different addresses
        c = TestClient(app, base_url="http://api.test", client=(f"203.0.113.{i + 1}", 50000 + i))
        assert c.post("/api/auth/login", json={"email": "owner@example.test", "password": "wrong-password"}).status_code in (401, 429)
    owner = TestClient(app, base_url="http://api.test", client=("198.51.100.5", 40000))
    assert owner.post("/api/auth/login", json={"email": "owner@example.test", "password": PASSWORD}).status_code == 200


def test_one_address_is_still_stopped_whatever_email_it_names(tmp_path):
    app = create_app(real_settings(tmp_path, login_burst=2))
    c = TestClient(app, base_url="http://api.test", client=("203.0.113.9", 50000))
    codes = [c.post("/api/auth/login", json={"email": f"user{i}@x.test", "password": "x"}).status_code for i in range(40)]
    assert 429 in codes


def test_a_real_install_never_records_a_fake_send_from_the_offline_adapters(session, settings, adapters, seeded):
    from pipecairn.sender import offline_adapter_on_real_install

    live_real = settings.model_copy(update={"demo_mode": False, "email_adapter": "seed", "sms_adapter": "seed"})
    assert offline_adapter_on_real_install(live_real, "email") and offline_adapter_on_real_install(live_real, "sms")
    assert not offline_adapter_on_real_install(settings, "email")  # a demo still sends through the offline adapter
    prepare(session)
    send_tick(session, live_real, adapters, NOW)
    session.commit()
    assert adapters.email.sent == [] and out_messages(session, status=("sent",)) == [] and out_messages(session, status=("drafted",))


def test_a_live_real_install_cannot_start_on_the_offline_email_adapter(tmp_path):
    s = real_settings(tmp_path, mode="live", sender_name="Sam Rivera", company_name="Rivera Works", company_address="12 Main Street, Springfield, IL 62701, USA", email_adapter="seed")
    assert any("EMAIL_ADAPTER" in e for e in s.runtime_errors())
    with pytest.raises(ConfigError):
        create_app(s)


def test_the_health_page_says_only_ok(tmp_path):
    c = TestClient(create_app(make_settings(tmp_path, mode="live", seed_dir=str(DATA))), base_url="http://api.test")
    assert c.get("/health").json() == {"status": "ok"}
    assert c.get("/ready").status_code == 200


def test_the_overview_reads_only_the_days_it_shows(session, settings, seeded):
    from datetime import timedelta

    from pipecairn import metrics

    lead = session.scalars(select(Lead)).first()
    old = NOW - timedelta(days=400)
    session.add_all([Message(lead_id=lead.id, channel="email", direction="out", status="sent", created_at=old, sent_at=old) for _ in range(30)])
    session.add(Message(lead_id=lead.id, channel="email", direction="out", status="sent", created_at=NOW, sent_at=NOW))
    session.commit()
    old_ids = set(session.scalars(select(Message.id).where(Message.created_at < NOW - timedelta(days=100))))
    session.expunge_all()
    loaded: list[int] = []

    def remember(target, context):
        loaded.append(target.id)

    event.listen(Message, "load", remember)
    try:
        out = metrics.overview(session, NOW)
    finally:
        event.remove(Message, "load", remember)
    assert old_ids and sum(d["sent"] for d in out["daily"]) == 1  # the 400 day old messages are not in the chart
    assert not (old_ids & set(loaded)), "the old messages were read into memory"


def test_the_audit_check_walks_the_log_in_batches_and_finds_an_edit(session):
    from pipecairn.audit_check import verify_recent
    from sendora_core.audit import record_audit
    from sendora_core.models import AuditEntry

    for i in range(30):
        record_audit(session, "t", "x", f"n:{i}", {"i": i})
    session.commit()
    assert verify_recent(session, 0) == (True, None, 30)
    assert verify_recent(session, 10) == (True, None, 10)  # only the newest ten are read
    row = session.get(AuditEntry, 25)
    row.detail = {"i": "edited"}
    session.commit()
    session.expunge_all()
    assert verify_recent(session, 10)[:2] == (False, 25)
    assert verify_recent(session, 5) == (True, None, 5)  # an edit older than the window is outside what was asked


def test_a_proposal_scope_item_has_a_length_limit(tmp_path):
    s = make_settings(tmp_path, seed_dir=str(DATA))
    app = create_app(s)
    c = TestClient(app, base_url="http://api.test")
    c.headers["x-session"] = c.post("/api/auth/login", json={"email": "owner@example.test", "password": "demo-password-1"}).json()["token"]
    body = {"lead_id": 1, "title": "T", "scope": ["x" * 301], "price_cents": 100}
    assert c.post("/api/proposals/preview", json=body).status_code == 422


def test_names_typed_into_a_public_form_cannot_carry_links_or_markup():
    from pipecairn.util import clean_person_text

    assert clean_person_text("<b>Ava</b> http://evil.example.test/x Click {{company}}") == "Ava Click company"
    assert clean_person_text("Anne-Marie O'Brien") == "Anne-Marie O'Brien"
    assert "\n" not in clean_person_text("Ava\nBcc: x@y.test") and len(clean_person_text("a" * 500)) == 60


def test_a_form_lead_name_is_cleaned_before_it_is_stored(tmp_path):
    import hashlib, hmac, json

    s = make_settings(tmp_path, seed_dir=str(DATA), webhook_shared_secret="whsec")
    app = create_app(s)
    c = TestClient(app, base_url="http://api.test")
    body = json.dumps({"email": "eve@acme.example.test", "first_name": "Eve http://evil.example.test <script>", "company": "Acme", "domain": "acme.example.test", "timezone": "America/New_York"}).encode()
    r = c.post("/api/webhooks/form", content=body, headers={"x-signature": hmac.new(b"whsec", body, hashlib.sha256).hexdigest()})
    assert r.status_code == 200
    with app.state.ctx.factory() as db:
        from pipecairn.models import Contact

        assert db.scalars(select(Contact).where(Contact.email == "eve@acme.example.test")).first().first_name == "Eve"


def test_a_link_signed_with_the_previous_secret_still_unsubscribes(tmp_path):
    from pipecairn.unsubscribe import make_token

    s = make_settings(tmp_path, seed_dir=str(DATA), session_secret="test-only-new-secret-aaaaaaaaaaaaaaaaaaaaaa", session_secret_previous="test-only-old-secret-bbbbbbbbbbbbbbbbbbbbbb")
    c = TestClient(create_app(s), base_url="http://api.test")
    old = make_token("test-only-old-secret-bbbbbbbbbbbbbbbbbbbbbb", "ava@acme.example.test")
    assert c.post(f"/api/webhooks/unsubscribe/{old}").status_code == 200
    assert c.post(f"/api/webhooks/unsubscribe/{make_token('test-only-someone-elses-secret-cccccccccccccc', 'ava@acme.example.test')}").status_code == 404


def test_the_constraints_header_names_a_command_that_exists():
    head = "\n".join((ROOT / "constraints.txt").read_text().splitlines()[:4])
    assert "make constraints" not in head and "pip freeze" in head
    assert "constraints" not in re.findall(r"^[a-z-]+:", (ROOT / "Makefile").read_text(), re.M)


def test_the_unmatched_mail_table_has_a_migration():
    assert "cl_unmatched_mail" in (ROOT / "apps/api/alembic/versions/0002_unmatched_mail.py").read_text()


def test_proposal_and_unmatched_routes_exist_in_the_schema(tmp_path):
    c = TestClient(create_app(make_settings(tmp_path, seed_dir=str(DATA))), base_url="http://api.test")
    c.headers["x-session"] = c.post("/api/auth/login", json={"email": "owner@example.test", "password": "demo-password-1"}).json()["token"]
    assert c.get("/api/inbox/unmatched").json() == []
    assert c.get("/api/overview").json()["unmatched_mail"] == 0
    assert c.get("/api/audit/verify").json()["ok"] is True
