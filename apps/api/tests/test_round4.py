"""Round 4: hostile mail cannot stall the worker, ordinary hot replies are not permanent opt outs, a resumed mailbox stays resumed,
a policy refusal is not a bad address, and one failing enrolment cannot block the others."""

import time
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from support import DATA, NOW, make_settings
from mock.mail_servers import StubMailServers
from pipecairn import intake, sender
from pipecairn.adapters import mailparse
from pipecairn.adapters.base import InboundEmail, RecipientRefused
from pipecairn.adapters.mailparse import parse_inbound
from pipecairn.adapters import smtp_imap
from pipecairn.adapters.smtp_imap import SmtpImapEmail
from pipecairn.api.app import create_app
from pipecairn.inbox import capture_email
from pipecairn.models import Activity, Enrollment, Lead, Mailbox, Message, Reply, Sequence
from pipecairn.replies import classify_reply
from pipecairn.sender import deliver, pick_mailbox, send_tick
from pipecairn.suppression import add_suppression, suppression_reason
from pipecairn.util import aware
from sendora_core.adapters import AdapterError
from sendora_core.models import AuditEntry
from test_inbox import cap, world  # noqa: F401  (the fixture and helpers of the inbox tests)

BOUND = 3.0  # seconds. A linear reader needs milliseconds (also under coverage); the quadratic ones took 10 to 30 seconds on these inputs.
HEAD = b"From: a@b.example.test\r\nTo: c@d.example.test\r\nSubject: x\r\n"


def timed(fn, *args, **kw):
    start = time.perf_counter()
    out = fn(*args, **kw)
    return out, time.perf_counter() - start


# ------------------------------------------------------------------ 1. the mail reader has limits

def test_unterminated_script_tags_are_read_in_linear_time():
    raw = HEAD + b"Content-Type: text/html\r\n\r\n" + b"<script " * 25_000  # 200 KB: about 15 seconds with the old pattern
    got, took = timed(parse_inbound, "1", raw)
    assert took < BOUND and got.from_addr == "a@b.example.test"


@pytest.mark.parametrize("header", ["From", "To"])
def test_a_header_made_of_quotes_is_read_in_linear_time(header):
    others = b"".join(line for name, line in ((b"From", b"From: a@b.example.test\r\n"), (b"To", b"To: c@d.example.test\r\n")) if name != header.encode())
    raw = others + b"Subject: x\r\n" + header.encode() + b": " + b'"' * 40_000 + b"\r\n\r\nhello\r\n"
    got, took = timed(parse_inbound, "1", raw)
    assert took < BOUND and "hello" in got.body


def test_a_hostile_header_inside_a_part_is_read_in_linear_time():
    raw = (HEAD + b"Content-Type: multipart/mixed; boundary=B\r\n\r\n--B\r\nContent-Type: text/plain; charset=" + b'"' * 40_000 + b"\r\n\r\nplease call me\r\n--B--\r\n")
    got, took = timed(parse_inbound, "1", raw)
    assert took < BOUND and got.from_addr == "a@b.example.test"


def test_unterminated_angle_brackets_and_nested_parts_are_read_in_linear_time():
    got, took = timed(parse_inbound, "1", HEAD + b"Content-Type: text/html\r\n\r\n" + b"<" * 250_000)
    assert took < BOUND
    deep = HEAD + b"Content-Type: multipart/mixed; boundary=a\r\n\r\n" + b"--a\r\nContent-Type: multipart/mixed; boundary=a\r\n\r\n" * 3000
    got, took = timed(parse_inbound, "1", deep)
    assert took < BOUND and got.from_addr


def test_a_very_large_message_is_read_from_its_first_part_and_flagged():
    raw = HEAD + b"\r\n" + b"Please send the details. " + b"filler line\r\n" * 80_000  # about 1 MB
    got, took = timed(parse_inbound, "1", raw)
    assert took < BOUND and "please send the details" in got.body.lower()
    assert "large" in got.parse_problem and len(got.body) <= mailparse.TEXT_LIMIT and not got.unreadable


def test_the_html_stripper_keeps_the_words_and_drops_scripts_and_tags():
    html = b"<html><style>p{color:red}</style><body><p>Yes, <b>interested</b>.</p><script>alert(1)</script>Call me &amp; soon<!-- note --></body></html>"
    got = parse_inbound("1", HEAD + b"Content-Type: text/html; charset=utf-8\r\n\r\n" + html)
    assert "interested" in got.body and "Call me & soon" in " ".join(got.body.split())
    assert "alert" not in got.body and "color" not in got.body and "<" not in got.body


def test_a_parse_that_takes_too_long_is_stopped_and_the_message_is_kept(monkeypatch):
    def slow(uid, raw):
        end = time.monotonic() + 3
        while time.monotonic() < end:
            pass
        raise AssertionError("the time limit never fired")

    monkeypatch.setattr(mailparse, "_parse", slow)
    monkeypatch.setattr(mailparse, "PARSE_SECONDS", 0.3)
    got, took = timed(parse_inbound, "7", HEAD + b"\r\nplease send details\r\n")
    assert took < 2.0 and got.unreadable and "too long" in got.parse_problem and got.uid == "7" and got.from_addr == "a@b.example.test"


def test_the_auto_reply_headers_are_read():
    def flag(extra):
        return parse_inbound("1", HEAD + extra + b"\r\nhi\r\n").auto_reply

    assert flag(b"Auto-Submitted: auto-replied\r\n") is True and flag(b"X-Autoreply: yes\r\n") is True and flag(b"Precedence: auto_reply\r\n") is True
    assert flag(b"Auto-Submitted: no\r\n") is False and flag(b"") is False


def imap_settings(tmp_path, srv):
    return make_settings(tmp_path, smtp_host=srv.host, imap_host=srv.host, imap_port=srv.imap_port, imap_use_ssl=False, smtp_user="demo", smtp_password="demo-password")


def test_the_inbox_fetch_is_capped_and_a_hostile_message_does_not_stall_it(tmp_path):
    hostile = HEAD + b"Content-Type: text/html\r\n\r\n" + b"<script " * 40_000  # 320 KB
    big = HEAD + b"\r\n" + b"I am interested, send times. " + b"x" * 900_000
    with StubMailServers() as srv:
        srv.store.deliver(hostile)
        srv.store.deliver(big)
        got, took = timed(SmtpImapEmail(imap_settings(tmp_path, srv)).fetch_replies)
    assert took < 4.0 and len(got) == 2
    assert all("large" in g.parse_problem for g in got)  # both went over the cap and say so
    assert "interested" in got[1].body


# ------------------------------------------------------------------ 2. a hot reply is not a permanent opt out

HOT = [
    "can we block this Thursday",
    "I'll loop in our legal team",
    "remove the setup fee",
    "please stop sending the PDFs, just call me",
    "forward to my attorney",
    "this unsolicited message is actually relevant",
]


def open_enrolments(session, lead):
    session.expire_all()
    return [e for e in session.scalars(select(Enrollment).where(Enrollment.lead_id == lead.id)) if e.status == "active"]


@pytest.mark.parametrize("text", HOT)
def test_ordinary_hot_wording_stops_the_sequence_but_never_suppresses(session, world, text):  # noqa: F811
    lead = world["lead"]
    assert open_enrolments(session, lead), "the fixture should leave the lead mid sequence"
    r = cap(session, world, text, ext="hot-" + str(abs(hash(text))))
    session.refresh(lead)
    assert not suppression_reason(session, email=lead.contact.email) and lead.status != "suppressed"
    assert r.handled is False and r.suggested_action != "suppressed"  # it is open in the inbox for a person
    assert not open_enrolments(session, lead)  # and nothing more goes out while it waits
    assert "request to stop" in r.summary  # the person reading it is told which wording made the reader careful


@pytest.mark.parametrize("text", HOT)
def test_the_same_sentences_are_not_certain_stops_for_the_reader(text):
    got = classify_reply(text, None)
    assert got.certain is False or got.intent != "unsubscribe"


def test_a_subject_that_is_ours_is_never_read_as_a_request(session, world):  # noqa: F811
    lead = world["lead"]
    for m in session.scalars(select(Message).where(Message.lead_id == lead.id, Message.direction == "out")):
        m.subject = "Stop writing follow up emails by hand"
    session.commit()
    mail = InboundEmail(external_id="subj-1", from_addr=lead.contact.email, to_addr="alex@mail.example.test", subject="Re: Stop writing follow up emails by hand", body="Yes, that sounds useful. Can we talk Thursday?")
    r = capture_email(session, world["settings"], world["llm"], world["adapters"].calendar, mail, NOW)
    session.commit()
    assert r.intent != "unsubscribe" and not suppression_reason(session, email=lead.contact.email)


def test_our_own_subject_is_ignored_but_a_typed_unsubscribe_subject_still_counts():
    ours = ["Unsubscribe fatigue is real"]
    assert classify_reply("Sounds good, call me", None, "Re: Unsubscribe fatigue is real", own_subjects=ours).intent != "unsubscribe"
    assert classify_reply("", None, "unsubscribe").intent == "unsubscribe"  # the subject a List-Unsubscribe mailto link sends
    assert classify_reply("", None, "Re: Unsubscribe", own_subjects=ours).intent == "unsubscribe"


@pytest.mark.parametrize("ours", ["Out of office? Not anymore", "Undeliverable mail is costing you leads", "Automatic reply for every enquiry"])
def test_our_own_subject_is_not_read_as_an_away_message_or_a_bounce(session, world, ours):  # noqa: F811
    lead = world["lead"]
    for m in session.scalars(select(Message).where(Message.lead_id == lead.id, Message.direction == "out")):
        m.subject = ours
    session.commit()
    mail = InboundEmail(external_id="own-" + str(abs(hash(ours))), from_addr=lead.contact.email, to_addr="alex@mail.example.test", subject="Re: " + ours, body="Sounds good, call me.")
    r = capture_email(session, world["settings"], world["llm"], world["adapters"].calendar, mail, NOW)
    session.commit()
    assert r.intent == "interested" and r.handled is False and r.approval_id is not None  # a draft is waiting for a person, nothing was filed away
    assert classify_reply("", None, "Automatic reply: " + ours, own_subjects=[ours]).intent in {"out_of_office", "bounce"}  # a real notice with the same words still counts


@pytest.mark.parametrize("text", ["STOPALL", "QUIT", "CANCEL", "END", "Please stop", "stop", "Unsubscribe", "please remove me from your list", "stop emailing me", "Do not contact me again."])
def test_complete_requests_and_carrier_words_suppress_at_once(session, world, text):  # noqa: F811
    lead = world["lead"]
    r = cap(session, world, text, ext="hard-" + str(abs(hash(text))))
    assert r.intent == "unsubscribe" and r.handled and suppression_reason(session, email=lead.contact.email) == "suppressed_email"


@pytest.mark.parametrize("text", ["cancel my Tuesday meeting", "end of quarter works for us", "we quit using that tool last year, what does yours do?"])
def test_a_carrier_word_inside_longer_text_is_not_a_stop(text):
    assert classify_reply(text, None).intent != "unsubscribe" or classify_reply(text, None).certain is False


def test_the_owner_can_lift_a_suppression_and_it_is_audited(tmp_path):
    app = create_app(make_settings(tmp_path, seed_dir=str(DATA)))
    with app.state.ctx.factory() as db:
        from pipecairn.seeding import load_seed, read_seed

        load_seed(db, read_seed(DATA), NOW)
        lead = db.scalars(select(Lead).where(Lead.status.notin_(("suppressed", "dead")))).first()
        add_suppression(db, "email", lead.contact.email, "asked to stop (reply)", "reply")
        lead.status = "suppressed"
        lead_id, addr = lead.id, lead.contact.email
        db.commit()

    def login(email):
        c = TestClient(app, base_url="http://api.test")
        c.headers["x-session"] = c.post("/api/auth/login", json={"email": email, "password": "demo-password-1"}).json()["token"]
        return c

    path = f"/api/leads/{lead_id}/lift-suppression"
    assert login("approver@example.test").post(path, json={"reason": "asked by phone"}).status_code == 403  # only the owner
    assert login("viewer@example.test").post(path, json={"reason": "not needed"}).status_code == 403
    owner = login("owner@example.test")
    assert owner.post("/api/leads/999999/lift-suppression", json={"reason": "not needed"}).status_code == 404
    assert owner.post(path, json={"reason": "wrote that it was a mistake"}).status_code == 200
    with app.state.ctx.factory() as db:
        assert not suppression_reason(db, email=addr)
        lead = db.get(Lead, lead_id)
        assert lead.status == "replied"  # a person is dealing with it: not put back into a sequence on its own
        acts = [e for e in db.scalars(select(AuditEntry)) if e.action == "suppression.lifted"]
        assert acts and "wrote that it was a mistake" in str(acts[-1].detail)
    assert owner.post(path, json={"reason": "again"}).status_code == 409  # nothing left to lift


# ------------------------------------------------------------------ 3. resuming a mailbox

def make_mailbox(session, **kw):
    base = dict(address="box@mail.example.test", daily_cap=50, sent_total=40, bounce_count=3, is_active=True, sent_day=NOW.date().isoformat())
    base.update(kw)
    mb = Mailbox(**base)
    session.add(mb)
    session.flush()
    return mb


def test_a_mailbox_paused_for_bounces_stays_resumed_after_resume(session):
    for mb in session.scalars(select(Mailbox)):
        mb.is_active = False
    box = make_mailbox(session)
    assert pick_mailbox(session, NOW) is None and box.is_active is False  # 3 of 40 is 7.5 percent: paused by the check
    sender.resume_mailbox(box)
    assert box.is_active and pick_mailbox(session, NOW) is box  # it was paused again at once before
    # the rate is counted from the resume: 2 more bounces in 20 more sends is 10 percent, so it pauses again
    box.sent_total, box.bounce_count = 60, 5
    assert pick_mailbox(session, NOW) is None and not box.is_active
    sender.resume_mailbox(box)
    box.sent_total += 20  # 20 clean sends since the second resume
    assert pick_mailbox(session, NOW) is box


def test_the_resume_route_uses_the_same_window(tmp_path):
    app = create_app(make_settings(tmp_path))
    with app.state.ctx.factory() as db:
        box = make_mailbox(db, is_active=False, paused_reason="Bounce rate above 5 percent. Fix the list, then resume by hand.")
        db.commit()
        box_id = box.id
    c = TestClient(app, base_url="http://api.test")
    c.headers["x-session"] = c.post("/api/auth/login", json={"email": "owner@example.test", "password": "demo-password-1"}).json()["token"]
    assert c.post(f"/api/deliverability/{box_id}/resume").status_code == 200
    with app.state.ctx.factory() as db:
        assert pick_mailbox(db, NOW) is not None  # the resumed mailbox is offered again and stays active
        assert db.get(Mailbox, box_id).is_active
        db.commit()


# ------------------------------------------------------------------ 4. which refusals are a bad address

@pytest.mark.parametrize("code,text,expected", [
    (550, "5.1.1 <a@b>: Recipient address rejected: User unknown", "bad_address"),
    (550, "No such user here", "bad_address"),
    (551, "User not local", "bad_address"),
    (553, "Mailbox name not allowed", "bad_address"),
    (554, "5.1.1 Bad destination mailbox address", "bad_address"),
    (554, "5.7.1 Service unavailable; Client host blocked using spamhaus", "policy"),
    (550, "5.7.1 Relay access denied", "policy"),
    (550, "Relay denied", "policy"),
    (554, "Transaction failed", "policy"),
    (554, "5.7.1 <a@b>: Recipient address rejected: Access denied", "policy"),
    (550, "5.4.1 Recipient address rejected: Access denied", "policy"),
    (552, "5.2.2 Mailbox full", "policy"),
])
def test_only_a_bad_address_refusal_is_one(code, text, expected):
    assert smtp_imap.refusal_kind(code, text) == expected


def send_to(tmp_path, srv, reply):
    srv.store.refuse_rcpt["ava@acme.example.test"] = reply
    s = make_settings(tmp_path, smtp_host=srv.host, smtp_port=srv.smtp_port, smtp_use_tls=False, smtp_user="demo", smtp_password="demo-password")
    return SmtpImapEmail(s).send(from_addr="sam@rivera.example.test", to="ava@acme.example.test", subject="Hi", body="Hello")


@pytest.mark.parametrize("reply", [550, "550 5.1.1 <ava@acme.example.test>: User unknown", "553 5.1.3 Bad address syntax", "551 User not local"])
def test_a_bad_address_refusal_is_a_hard_bounce(tmp_path, reply):
    with StubMailServers() as srv, pytest.raises(RecipientRefused):
        send_to(tmp_path, srv, reply)


@pytest.mark.parametrize("reply", ["554 5.7.1 <ava@acme.example.test>: Relay access denied", "550 5.7.1 Service unavailable; client host blocked using rbl.example.test", "554 Transaction failed", "450 4.2.0 Try again later"])
def test_a_policy_or_server_refusal_is_not_a_bad_address(tmp_path, reply):
    with StubMailServers() as srv:
        with pytest.raises(AdapterError) as e:
            send_to(tmp_path, srv, reply)
    assert not isinstance(e.value, RecipientRefused)
    assert getattr(e.value, "message_specific", True) is False or reply.startswith("450")  # a server problem never counts against the lead


def test_a_policy_refusal_suppresses_nobody_and_counts_no_bounce(session, world, tmp_path):  # noqa: F811
    lead = world["lead"]
    mb = session.scalars(select(Mailbox).where(Mailbox.is_active.is_(True))).first()
    before = (mb.bounce_count, lead.status)
    with StubMailServers() as srv:
        srv.store.refuse_rcpt[lead.contact.email] = "554 5.7.1 Relay access denied"
        s = make_settings(tmp_path, smtp_host=srv.host, smtp_port=srv.smtp_port, smtp_use_tls=False, smtp_user="demo", smtp_password="demo-password")
        world["adapters"].email = SmtpImapEmail(s)
        status, _ = deliver(session, world["settings"], world["adapters"], lead=lead, enr=None, channel="email", subject="Hi", body="Hello", now=NOW, respect_quiet=False)
    session.commit()
    assert status == "failed"
    assert (mb.bounce_count, lead.status) == before and not suppression_reason(session, email=lead.contact.email)
    assert any(e.action == "mailbox.server_refusal" for e in session.scalars(select(AuditEntry)))  # the mailbox gets a note


def test_a_bad_address_refusal_still_suppresses_and_counts(session, world, tmp_path):  # noqa: F811
    lead = world["lead"]
    with StubMailServers() as srv:
        srv.store.refuse_rcpt[lead.contact.email] = "550 5.1.1 User unknown"
        s = make_settings(tmp_path, smtp_host=srv.host, smtp_port=srv.smtp_port, smtp_use_tls=False, smtp_user="demo", smtp_password="demo-password")
        world["adapters"].email = SmtpImapEmail(s)
        status, reason = deliver(session, world["settings"], world["adapters"], lead=lead, enr=None, channel="email", subject="Hi", body="Hello", now=NOW, respect_quiet=False)
    assert (status, reason) == ("stop", "recipient_refused") and lead.status == "dead"


# ------------------------------------------------------------------ 5. bounce and out of office need proof

@pytest.mark.parametrize("text", ["Your mail was refused by our spam filter, but I am interested. Send times.", "We bounced between vendors for a year. Tell me more."])
def test_a_reply_that_only_sounds_like_a_bounce_stops_the_sequence_and_stays_open(session, world, text):  # noqa: F811
    lead = world["lead"]
    r = cap(session, world, text, ext="ub-" + str(abs(hash(text))))
    assert r.handled is False
    assert not open_enrolments(session, lead)  # the next step must not go out to a person who just answered
    assert not suppression_reason(session, email=lead.contact.email)


def test_an_away_wording_without_proof_is_not_handled_for_you(session, world):  # noqa: F811
    for n, text in enumerate(["Can we meet? I'm back in the office next Tuesday.", "Re ticket #4412: yes, call me about the pilot."]):
        lead = world["lead"]
        r = cap(session, world, text, ext=f"ooo-{n}")
        assert r.handled is False, text  # a person reads it; it was hidden as handled before
        assert not open_enrolments(session, lead)


def test_an_auto_reply_with_the_header_or_the_words_is_still_handled(session, world):  # noqa: F811
    r = cap(session, world, "Thank you. We have received your request. Ticket #4412.", ext="auto-1", auto_reply=True)
    assert r.intent == "out_of_office" and r.handled is True
    r = cap(session, world, "I am out of the office until 3 December with limited access to email.", ext="auto-2")
    assert r.intent == "out_of_office" and r.handled is True


# ------------------------------------------------------------------ 7. one failing enrolment cannot block the rest

def make_due(session, n=4):
    """n enrolments mid sequence, all due now. Returns them oldest first."""
    rows = list(session.scalars(select(Enrollment).where(Enrollment.status == "active").order_by(Enrollment.id)))[:n]
    assert len(rows) == n
    for i, e in enumerate(rows):
        e.next_send_at = NOW - timedelta(minutes=10 - i)
    session.commit()
    return rows


def test_one_failing_enrolment_does_not_block_the_others(session, world, monkeypatch):  # noqa: F811
    bad, *rest = make_due(session)
    bad_id, rest_ids = bad.id, [e.id for e in rest]
    real = sender._tick_enrollment

    def flaky(session_, settings, adapters, enr, now, report):
        if enr.id == bad_id:
            raise ValueError("this one row is broken")
        return real(session_, settings, adapters, enr, now, report)

    monkeypatch.setattr(sender, "_tick_enrollment", flaky)
    sent_before = len(world["adapters"].email.sent)
    rep = send_tick(session, world["settings"], world["adapters"], NOW)
    session.commit()
    assert rep.errors == 1 and len(world["adapters"].email.sent) > sent_before  # the rows behind it were still sent
    assert any(session.get(Enrollment, i).current_step >= 1 for i in rest_ids)
    session.expire_all()
    bad = session.get(Enrollment, bad_id)
    assert bad.status == "active" and aware(bad.next_send_at) > NOW  # moved out of the front of the queue
    assert any("could not be prepared" in a.summary for a in session.scalars(select(Activity).where(Activity.lead_id == bad.lead_id)))


def test_an_enrolment_that_keeps_failing_is_moved_aside(session, world, monkeypatch):  # noqa: F811
    bad = make_due(session, 1)[0]
    bad_id = bad.id

    def always(*a, **k):
        raise ValueError("broken")

    monkeypatch.setattr(sender, "_tick_enrollment", always)
    for k in range(sender.MAX_TICK_ERRORS):
        session.expire_all()
        session.get(Enrollment, bad_id).next_send_at = NOW - timedelta(minutes=1)
        session.commit()
        send_tick(session, world["settings"], world["adapters"], NOW + timedelta(hours=k))
        session.commit()
    session.expire_all()
    bad = session.get(Enrollment, bad_id)
    assert bad.status == "stopped" and bad.stop_reason == "send_error"


def test_a_database_outage_is_not_blamed_on_one_enrolment(session, world, monkeypatch):  # noqa: F811
    from sqlalchemy.exc import OperationalError

    make_due(session, 2)

    def down(*a, **k):
        raise OperationalError("select 1", {}, Exception("connection lost"))

    monkeypatch.setattr(sender, "_tick_enrollment", down)
    with pytest.raises(OperationalError):
        send_tick(session, world["settings"], world["adapters"], NOW)
    session.rollback()
    assert all(e.status == "active" for e in session.scalars(select(Enrollment).where(Enrollment.status != "done", Enrollment.status != "stopped", Enrollment.status != "paused")))


def test_a_rendered_subject_is_clipped_to_what_the_column_holds(session, world):  # noqa: F811
    seq = session.scalars(select(Sequence)).first()
    for st in seq.steps:
        st.subject = "Quick question about {{company}} " + "x" * 400
    e = make_due(session, 1)[0]
    session.commit()
    send_tick(session, world["settings"], world["adapters"], NOW)
    session.commit()
    outs = [m for m in session.scalars(select(Message).where(Message.enrollment_id == e.id, Message.direction == "out"))]
    assert outs and all(len(m.subject) <= 300 for m in outs)
    assert all(len(s["subject"]) <= 300 for s in world["adapters"].email.sent)


# ------------------------------------------------------------------ lows

def test_the_csv_importer_cleans_names_like_the_web_form(session):
    rows = [{"first_name": "Ava <b>x</b> https://evil.example.test", "last_name": "{{company}}", "email": "ava.clean@acme.example.test", "title": "Owner\nBcc: spy@x.test", "company": "Acme", "domain": "acme.example.test", "timezone": "America/New_York"}]
    intake.import_leads(session, rows, NOW, default_source="csv", default_timezone="America/New_York")
    session.commit()
    lead = session.scalars(select(Lead).join(Lead.contact).where(Lead.contact.has(email="ava.clean@acme.example.test"))).first()
    c = lead.contact
    for field in (c.first_name, c.last_name, c.title):
        assert "<" not in field and "http" not in field and "{{" not in field and "\n" not in field


def test_the_email_webhook_takes_the_auto_submitted_header_from_a_relay(tmp_path):
    import hashlib
    import hmac
    import json

    app = create_app(make_settings(tmp_path, seed_dir=str(DATA), webhook_shared_secret="whsec"))
    c = TestClient(app, base_url="http://api.test")

    def post(payload):
        body = json.dumps(payload).encode()
        return c.post("/api/webhooks/email", content=body, headers={"x-signature": hmac.new(b"whsec", body, hashlib.sha256).hexdigest()}).json()

    lead = json.dumps({"email": "ava@acme.example.test", "first_name": "Ava", "company": "Acme", "domain": "acme.example.test", "timezone": "America/New_York"}).encode()
    assert c.post("/api/webhooks/form", content=lead, headers={"x-signature": hmac.new(b"whsec", lead, hashlib.sha256).hexdigest()}).json()["created"] == 1
    base = {"from": "ava@acme.example.test", "to": "sam@x.test", "subject": "Re: hi", "text": "We have received your request. Ticket #4412."}
    assert post({**base, "message_id": "w1"})["captured"] is True
    assert post({**base, "message_id": "w2", "auto_submitted": "auto-replied"})["captured"] is True
    with app.state.ctx.factory() as s:
        by_id = {m.external_id: s.scalars(select(Reply).where(Reply.message_id == m.id)).first() for m in s.scalars(select(Message).where(Message.direction == "in"))}
    assert by_id["w1"].handled is False and by_id["w1"].suggested_action == "check_auto_reply"  # no header: a person reads it
    assert by_id["w2"].handled is True and by_id["w2"].suggested_action == "wait"  # the relay said it is an automatic reply


def test_an_existing_sqlite_file_gets_the_new_mailbox_columns_at_start(tmp_path):
    from sqlalchemy import inspect, text

    from pipecairn.dbupgrade import create_and_upgrade
    from sendora_core.db import Base, make_engine

    engine = make_engine(f"sqlite:///{tmp_path / 'old.sqlite3'}")
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE cl_mailbox DROP COLUMN sent_base"))
        conn.execute(text("ALTER TABLE cl_mailbox DROP COLUMN bounce_base"))
    added = create_and_upgrade(engine)
    assert {"cl_mailbox.sent_base", "cl_mailbox.bounce_base"} <= set(added)
    assert {"sent_base", "bounce_base"} <= {c["name"] for c in inspect(engine).get_columns("cl_mailbox")}
