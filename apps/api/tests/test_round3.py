"""Round 3 review: mail that cannot be read, an opt out worded like a bounce, a send that was cut off, a relay that refuses, delay notices, and the smaller findings.
Every mail here is real bytes read by the real parser and the real classifier through the fake IMAP server, not a scripted adapter."""

import base64

import pytest
from sqlalchemy import select

from mock.mail_servers import FakeMailServers
from pipecairn.adapters.smtp_imap import SmtpImapEmail
from pipecairn.context import Ctx
from pipecairn.jobs import job_reply_poll
from pipecairn.models import Enrollment, Lead, Mailbox, Message, Reply, Suppression, UnmatchedMail
from pipecairn.replies import classify_reply
from pipecairn.suppression import suppression_reason
from support import NOW, Adapters, make_settings
from test_inbox import world  # noqa: F401  (the fixture of the inbox tests)


def mail_settings(tmp_path, srv, **extra):
    return make_settings(tmp_path, smtp_host=srv.host, smtp_port=srv.smtp_port, smtp_use_tls=False, smtp_user="demo", smtp_password="demo-password",
                         imap_host=srv.host, imap_port=srv.imap_port, imap_use_ssl=False, **extra)


def raw_mail(sender, body, *, headers="", ctype="text/plain; charset=utf-8", encoding="7bit", msg_id="m1@x.example.test", subject="Re: hi") -> bytes:
    head = (f"From: Ava <{sender}>\r\nTo: alex@mail.example.test\r\nSubject: {subject}\r\nMessage-ID: <{msg_id}>\r\nMIME-Version: 1.0\r\n"
            f"Content-Type: {ctype}\r\nContent-Transfer-Encoding: {encoding}\r\n{headers}\r\n").encode()
    return head + (body if isinstance(body, bytes) else body.encode()) + b"\r\n"


class Polled:
    """A real IMAP poll: the real adapter against the fake server, the real job, the real database."""

    def __init__(self, session, factory, world, tmp_path, srv):
        self.session, self.world, self.srv = session, world, srv
        self.email = SmtpImapEmail(mail_settings(tmp_path, srv))
        self.ctx = Ctx(world["settings"], factory)
        self.ctx.adapters = Adapters(world["settings"])
        self.ctx.adapters.email = self.email

    def poll(self):
        out = job_reply_poll(self.session, self.ctx)
        self.session.rollback()
        return out

    def seen(self):
        return [m["seen"] for m in self.srv.store.inbox]


@pytest.fixture
def polled(session, factory, world, tmp_path):  # noqa: F811
    with FakeMailServers() as srv:
        yield Polled(session, factory, world, tmp_path, srv)


def lead_email(world) -> str:  # noqa: F811
    return world["lead"].contact.email


# ---------------------------------------------------------------- HIGH 1. one unreadable message must not stop the inbox

def nested_multipart(depth: int, sender: str) -> bytes:
    parts = [f"From: Ava <{sender}>\r\nTo: a@b.example.test\r\nSubject: Re: hi\r\nMessage-ID: <deep@x.example.test>\r\nMIME-Version: 1.0\r\n"]
    for i in range(depth):
        parts.append(f"Content-Type: multipart/mixed; boundary=B{i}\r\n\r\n--B{i}\r\n")
    parts.append("Content-Type: text/plain\r\n\r\nSTOP\r\n")
    return "".join(parts).encode()


def bad_mails(sender: str) -> dict[str, bytes]:
    return {
        "unknown charset": raw_mail(sender, "please send details", ctype="text/plain; charset=foo-bar", msg_id="bad1@x.example.test"),
        "broken base64": raw_mail(sender, "@@@@ not base64 !!!! ====", encoding="base64", msg_id="bad2@x.example.test"),
        "huge header": raw_mail(sender, "hello there", headers="X-Junk: " + "a" * 300_000 + "\r\n", msg_id="bad3@x.example.test"),
        "nested multipart": nested_multipart(600, sender),
        "missing parts": (f"From: Ava <{sender}>\r\nTo: a@b.example.test\r\nSubject: Re: hi\r\nMessage-ID: <bad5@x.example.test>\r\nMIME-Version: 1.0\r\n"
                          "Content-Type: multipart/mixed; boundary=ZZ\r\n\r\n--ZZ\r\n").encode(),
        "no body at all": f"From: Ava <{sender}>\r\nSubject: Re: hi\r\nMessage-ID: <bad6@x.example.test>\r\n\r\n".encode(),
        "bad charset in the second part": (f"From: Ava <{sender}>\r\nTo: a@b.example.test\r\nSubject: Re: hi\r\nMessage-ID: <bad7@x.example.test>\r\nMIME-Version: 1.0\r\n"
                                           "Content-Type: multipart/alternative; boundary=QQ\r\n\r\n--QQ\r\nContent-Type: text/plain; charset=no-such-charset\r\n\r\nplease stop\r\n"
                                           "--QQ\r\nContent-Type: text/html; charset=utf-8\r\n\r\n<p>x</p>\r\n--QQ--\r\n").encode(),
    }


@pytest.mark.parametrize("name", list(bad_mails("x@y.example.test")))
def test_one_unreadable_message_does_not_stop_the_inbox_and_the_stop_behind_it_is_stored(name, session, polled, world):  # noqa: F811
    polled.srv.store.deliver(bad_mails(lead_email(world))[name])
    polled.srv.store.deliver(raw_mail(lead_email(world), "STOP emailing me please", msg_id="good@x.example.test"))
    for _ in range(3):
        polled.poll()  # the old code raised LookupError at the first message on every poll
    assert suppression_reason(session, email=lead_email(world)) == "suppressed_email", name
    assert polled.seen()[1] is True  # the good one was stored, then marked read
    assert len(list(session.scalars(select(Message).where(Message.direction == "in")))) == 2, "the unreadable message itself must be kept, not dropped"


def test_a_message_with_an_unknown_charset_is_kept_as_text_flagged_and_marked_read(session, polled, world):  # noqa: F811
    polled.srv.store.deliver(bad_mails(lead_email(world))["unknown charset"])
    out = polled.poll()
    assert out["captured"] == 1 and out["failed"] == 0
    msg = session.scalars(select(Message).where(Message.direction == "in")).first()
    assert "please send details" in msg.body and msg.blocked_reason.startswith("parse:")
    assert polled.seen() == [True]
    assert polled.poll()["captured"] == 0  # not fetched again


def test_a_stop_written_in_an_unknown_charset_still_suppresses(session, polled, world):  # noqa: F811
    polled.srv.store.deliver(raw_mail(lead_email(world), "STOP emailing me", ctype="text/plain; charset=foo-bar", msg_id="s1@x.example.test"))
    polled.poll()
    assert suppression_reason(session, email=lead_email(world)) == "suppressed_email"


def test_a_message_that_cannot_be_parsed_at_all_is_stored_as_unreadable_mail_for_a_person(session, polled, world):  # noqa: F811
    polled.srv.store.deliver(nested_multipart(5000, lead_email(world)))
    out = polled.poll()
    assert out["failed"] == 0 and polled.seen() == [True]
    reply = session.scalars(select(Reply)).first()
    assert reply is not None and reply.suggested_action == "unreadable_mail" and reply.handled is False
    assert reply.draft_reply == "" and reply.approval_id is None  # nothing is drafted or sent from garbage
    lead = session.get(Lead, world["lead"].id)
    assert lead.status == "replied"  # the person wrote back, so the sequence stops until a human has read it
    assert not [e for e in session.scalars(select(Enrollment).where(Enrollment.lead_id == lead.id)) if e.status == "active"]


def test_unreadable_mail_from_a_stranger_is_kept_flagged_without_its_text(session, polled, world):  # noqa: F811
    polled.srv.store.deliver(nested_multipart(5000, "stranger@elsewhere.example.test"))
    polled.poll()
    row = session.scalars(select(UnmatchedMail)).one()
    assert row.flag == "unreadable" and row.from_addr == "stranger@elsewhere.example.test" and row.snippet == "" and polled.seen() == [True]


# ---------------------------------------------------------------- HIGH 2. a request to stop wins over bounce wording

STOP_WORDED_LIKE_A_BOUNCE = [
    "Please unsubscribe me, this address is no longer used",
    "remove me, this mailbox is no longer monitored",
    "Take me off your list. This email address is no longer active.",
    "Stop emailing me. Mail delivery failed anyway, so this account is closed.",
    "I want to opt out. The mailbox is full and I do not read it any more.",
    "Do not contact me again, the address does not exist for me any more.",
    "Unsubscribe. Your message could not be delivered to my old team, please remove this address.",
    "Please stop writing to me. This mailbox is unavailable and unmonitored.",
]


@pytest.mark.parametrize("text", STOP_WORDED_LIKE_A_BOUNCE)
def test_an_opt_out_that_uses_bounce_wording_is_still_an_opt_out(text):
    assert classify_reply(text, None, "Re: hi").intent == "unsubscribe"


@pytest.mark.parametrize("text", STOP_WORDED_LIKE_A_BOUNCE[:4])
def test_such_an_opt_out_suppresses_the_lead_through_the_real_inbox(text, session, polled, world):  # noqa: F811
    polled.srv.store.deliver(raw_mail(lead_email(world), text, msg_id="o1@x.example.test"))
    polled.poll()
    assert suppression_reason(session, email=lead_email(world)) == "suppressed_email"
    assert session.get(Lead, world["lead"].id).status == "suppressed"
    assert not [e for e in session.scalars(select(Enrollment).where(Enrollment.lead_id == world["lead"].id)) if e.status == "active"]


def test_a_plain_unverified_bounce_guess_is_still_only_a_guess(session, polled, world):  # noqa: F811
    polled.srv.store.deliver(raw_mail(lead_email(world), "Mail delivery failed: the address was not found.", msg_id="g1@x.example.test"))
    polled.poll()
    reply = session.scalars(select(Reply)).one()
    assert reply.intent == "bounce" and reply.suggested_action == "unverified_bounce"
    assert not suppression_reason(session, email=lead_email(world))


# ---------------------------------------------------------------- MEDIUM 5. a delivery report says what happened in its own Action and Status lines

def delivery_report(sent_id: str, action: str, status: str, recipient: str, *, text: str = "This is the mail system at host mx.example.test.", n: int = 1) -> bytes:
    sid = "<" + sent_id.strip("<>") + ">"
    return (f"From: MAILER-DAEMON@mx.example.test\r\nTo: alex@mail.example.test\r\nSubject: Delivery Status Notification\r\nMessage-ID: <dsn-{n}@mx.example.test>\r\n"
            f"Authentication-Results: mx; spf=pass\r\nMIME-Version: 1.0\r\nContent-Type: multipart/report; report-type=delivery-status; boundary=B\r\n\r\n"
            f"--B\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n{text}\r\n"
            f"--B\r\nContent-Type: message/delivery-status\r\n\r\nReporting-MTA: dns; mx.example.test\r\n\r\nFinal-Recipient: rfc822; {recipient}\r\nAction: {action}\r\nStatus: {status}\r\n"
            f"Diagnostic-Code: smtp; {status}\r\n\r\n"
            f"--B\r\nContent-Type: text/rfc822-headers\r\n\r\nMessage-ID: {sid}\r\nSubject: Hi\r\n\r\n--B--\r\n").encode()


def our_sent_id(session, world) -> str:  # noqa: F811
    return session.scalars(select(Message).where(Message.lead_id == world["lead"].id, Message.direction == "out", Message.status == "sent")).first().external_id


DELAYED = [
    ("delayed", "4.4.1", "Delivery to the following recipient has been delayed. The server will keep trying to deliver the message for 2 days."),
    ("delayed", "4.2.2", "The recipient's mailbox is full. Delivery is delayed."),
    ("failed", "4.2.2", "The mailbox is over quota (temporary)."),
    ("delayed", "4.7.0", "Temporary failure: the receiving server asked us to try again later (greylisting)."),
]


@pytest.mark.parametrize(("action", "status", "text"), DELAYED)
def test_a_delivery_delayed_notice_changes_nothing(action, status, text, session, polled, world):  # noqa: F811
    mb = session.scalars(select(Mailbox).where(Mailbox.id == session.scalars(select(Message).where(Message.lead_id == world["lead"].id, Message.status == "sent")).first().mailbox_id)).one()
    before = (mb.bounce_count, session.get(Lead, world["lead"].id).status)
    polled.srv.store.deliver(delivery_report(our_sent_id(session, world), action, status, lead_email(world), text=text))
    polled.poll()
    session.expire_all()
    assert not suppression_reason(session, email=lead_email(world)), (action, status)
    assert (session.get(Mailbox, mb.id).bounce_count, session.get(Lead, world["lead"].id).status) == before
    assert not list(session.scalars(select(Reply))) and polled.seen() == [True]


@pytest.mark.parametrize("status", ["5.1.1", "5.7.1", "5.2.1", "5.4.1"])
def test_a_permanent_failure_report_suppresses_the_address_and_counts_against_the_mailbox(status, session, polled, world):  # noqa: F811
    mb_id = session.scalars(select(Message).where(Message.lead_id == world["lead"].id, Message.status == "sent")).first().mailbox_id
    before = session.get(Mailbox, mb_id).bounce_count
    polled.srv.store.deliver(delivery_report(our_sent_id(session, world), "failed", status, lead_email(world), text="Your message could not be delivered."))
    polled.poll()
    session.expire_all()
    assert suppression_reason(session, email=lead_email(world)) == "suppressed_email"
    assert session.get(Lead, world["lead"].id).status == "dead" and session.get(Mailbox, mb_id).bounce_count == before + 1
    assert session.scalars(select(Reply)).one().suggested_action == "suppressed"


def test_a_permanent_failure_with_unusual_wording_is_still_a_bounce_because_the_status_lines_say_so(session, polled, world):  # noqa: F811
    polled.srv.store.deliver(delivery_report(our_sent_id(session, world), "failed", "5.1.1", lead_email(world), text="Hello. We have a problem with your note. Please see below."))
    polled.poll()
    assert suppression_reason(session, email=lead_email(world)) == "suppressed_email"


def test_an_auto_reply_is_read_as_an_auto_reply_not_a_bounce(session, polled, world):  # noqa: F811
    polled.srv.store.deliver(raw_mail(lead_email(world), "I am out of the office until Monday with limited access to email.", subject="Automatic reply: Hi", msg_id="ooo@x.example.test"))
    polled.poll()
    assert session.scalars(select(Reply)).one().intent == "out_of_office" and not suppression_reason(session, email=lead_email(world))


def test_a_report_that_does_not_say_whether_it_failed_is_left_for_a_person(session, polled, world):  # noqa: F811
    bare = delivery_report(our_sent_id(session, world), "failed", "5.1.1", lead_email(world), text="Something happened.").replace(b"Action: failed\r\nStatus: 5.1.1\r\n", b"").replace(b"Diagnostic-Code: smtp; 5.1.1\r\n", b"")
    polled.srv.store.deliver(bare)
    polled.poll()
    reply = session.scalars(select(Reply)).one()
    assert reply.intent == "bounce" and reply.suggested_action == "unverified_bounce" and not reply.handled and not reply.draft_reply
    assert not suppression_reason(session, email=lead_email(world))


def test_a_report_that_says_failed_but_gives_no_status_is_left_for_a_person(session, polled, world):  # noqa: F811
    no_status = delivery_report(our_sent_id(session, world), "failed", "5.1.1", lead_email(world), text="Something happened.").replace(b"Status: 5.1.1\r\n", b"").replace(b"Diagnostic-Code: smtp; 5.1.1\r\n", b"")
    polled.srv.store.deliver(no_status)
    polled.poll()
    assert session.scalars(select(Reply)).one().suggested_action == "unverified_bounce" and not suppression_reason(session, email=lead_email(world))


def test_the_report_that_matches_no_message_of_ours_is_ignored(session, polled, world):  # noqa: F811
    polled.srv.store.deliver(delivery_report("<not-ours@x.example.test>", "failed", "5.1.1", lead_email(world)))
    polled.poll()
    assert not suppression_reason(session, email=lead_email(world))


def test_delivery_status_is_read_from_the_report_lines():
    import email
    from email.policy import default

    from pipecairn.adapters.mailparse import delivery_status_of

    two = delivery_report("<a@b.example.test>", "delayed", "4.4.1", "x@y.example.test").replace(
        b"Diagnostic-Code: smtp; 4.4.1\r\n\r\n", b"Diagnostic-Code: smtp; 4.4.1\r\n\r\nFinal-Recipient: rfc822; z@y.example.test\r\nAction: failed\r\nStatus: 5.1.1\r\n\r\n")
    assert delivery_status_of(email.message_from_bytes(two, policy=default)) == ("failed", "5.1.1")  # a permanent failure in any group decides
    assert delivery_status_of(email.message_from_bytes(raw_mail("a@b.example.test", "hi"), policy=default)) == ("", "")


# ---------------------------------------------------------------- MEDIUM 3. a message cut off mid send is never sent again, however late the restart

from datetime import timedelta  # noqa: E402

from pipecairn.sender import MAX_SEND_ATTEMPTS, STEP_COUNTED, mark_not_sent, send_tick  # noqa: E402
from sendora_core.adapters import AdapterError  # noqa: E402
from support import RecordingEmail  # noqa: E402
from test_round2 import Crash, CrashingEmail  # noqa: E402
from test_sender import out_messages, prepare  # noqa: E402


@pytest.mark.parametrize("minutes_later", [0, 5, 20, 45])
def test_a_message_that_was_sending_when_the_worker_died_is_not_sent_again_at_any_restart_time(minutes_later, session, settings, adapters, seeded):
    prepare(session)
    adapters.email = CrashingEmail(settings, after=3)
    with pytest.raises(Crash) as died:
        send_tick(session, settings, adapters, NOW)
    session.rollback()
    sent_before = {m["to"] for m in adapters.email.sent}
    restart = NOW + timedelta(minutes=minutes_later)
    adapters.email = RecordingEmail(settings)
    send_tick(session, settings, adapters, restart)
    session.commit()
    again = {m["to"] for m in adapters.email.sent}
    assert died.value.to not in again, f"mailed a second time after a restart {minutes_later} minutes later"
    assert not (again & sent_before)
    unconfirmed = [m for m in out_messages(session, status=("unconfirmed",)) if m.to_addr == died.value.to]
    assert len(unconfirmed) == 1 and not out_messages(session, status=("sending",))
    enr = session.get(Enrollment, unconfirmed[0].enrollment_id)
    assert enr.current_step == 1  # the step counts as done, once
    send_tick(session, settings, adapters, restart + timedelta(minutes=5))  # and a later run does not account for it a second time
    session.commit()
    assert session.get(Enrollment, unconfirmed[0].enrollment_id).current_step == 1


def test_a_person_can_mark_an_unconfirmed_message_as_not_sent_so_it_is_tried_again(session, settings, adapters, seeded):
    prepare(session)
    adapters.email = CrashingEmail(settings, after=1)
    with pytest.raises(Crash) as died:
        send_tick(session, settings, adapters, NOW)
    session.rollback()
    adapters.email = RecordingEmail(settings)
    send_tick(session, settings, adapters, NOW + timedelta(minutes=30))
    session.commit()
    m = next(x for x in out_messages(session, status=("unconfirmed",)) if x.to_addr == died.value.to)
    assert mark_not_sent(session, m.id, decided_by="owner", now=NOW + timedelta(minutes=31)) == "retry"
    session.commit()
    assert m.status == "not_sent"
    send_tick(session, settings, adapters, NOW + timedelta(minutes=32))
    session.commit()
    assert died.value.to in {x["to"] for x in adapters.email.sent}  # now it is sent, because a person said it never left
    with pytest.raises(ValueError):
        mark_not_sent(session, m.id, decided_by="owner", now=NOW)  # only an unconfirmed message can be reopened, so never twice


def test_a_message_left_sending_while_the_person_asked_to_wait_is_not_sent_when_the_pause_ends(session, settings, adapters, seeded):
    """The worker dies mid send, then an out of office reply pauses the enrolment, then the restart comes late (the sweep finds a paused enrolment)."""
    prepare(session)
    adapters.email = CrashingEmail(settings, after=2)
    with pytest.raises(Crash) as died:
        send_tick(session, settings, adapters, NOW)
    session.rollback()
    victim = next(m for m in out_messages(session, status=("sending",)) if m.to_addr == died.value.to)
    enr = session.get(Enrollment, victim.enrollment_id)
    enr.status, enr.next_send_at, enr.paused_until = "paused", None, NOW + timedelta(days=2)  # what the reader does for an out of office reply
    session.commit()
    adapters.email = RecordingEmail(settings)
    send_tick(session, settings, adapters, NOW + timedelta(minutes=20))
    session.commit()
    assert session.get(Message, victim.id).status == "unconfirmed" and session.get(Enrollment, enr.id).status == "paused"
    send_tick(session, settings, adapters, NOW + timedelta(days=2, hours=1))  # the pause is over: the enrolment wakes
    session.commit()
    again = [m for m in adapters.email.sent if m["to"] == died.value.to]
    assert not again, "the step that was cut off was sent when the pause ended"
    assert session.get(Enrollment, enr.id).current_step == 1 and STEP_COUNTED in session.get(Message, victim.id).blocked_reason
    send_tick(session, settings, adapters, NOW + timedelta(days=2, hours=2))
    session.commit()
    assert session.get(Enrollment, enr.id).current_step == 1  # counted once


def test_an_unconfirmed_message_left_by_an_older_version_is_counted_before_anything_is_sent(session, settings, adapters, seeded):
    prepare(session)
    enr = one_enrollment(session)
    old = Message(lead_id=enr.lead_id, enrollment_id=enr.id, channel="email", direction="out", to_addr=enr.lead.contact.email, status="unconfirmed", blocked_reason="worker_stopped_during_send", created_at=NOW - timedelta(hours=1))
    session.add(old)
    session.commit()
    send_tick(session, settings, adapters, NOW)
    session.commit()
    assert not adapters.email.sent and session.get(Enrollment, enr.id).current_step == 1


def test_marking_a_message_not_sent_while_the_person_is_paused_waits_for_the_pause(session, settings, adapters, seeded):
    prepare(session)
    adapters.email = CrashingEmail(settings, after=1)
    with pytest.raises(Crash) as died:
        send_tick(session, settings, adapters, NOW)
    session.rollback()
    victim = next(m for m in out_messages(session, status=("sending",)) if m.to_addr == died.value.to)
    enr = session.get(Enrollment, victim.enrollment_id)
    enr.status, enr.next_send_at, enr.paused_until = "paused", None, NOW + timedelta(days=2)
    session.commit()
    adapters.email = RecordingEmail(settings)
    send_tick(session, settings, adapters, NOW + timedelta(days=2, minutes=1))  # wakes, counts the step as done
    session.commit()
    assert mark_not_sent(session, victim.id, decided_by="owner", now=NOW + timedelta(days=3)) == "retry"
    assert session.get(Enrollment, enr.id).current_step == 0
    enr.status, enr.paused_until = "paused", NOW + timedelta(days=5)  # asked to wait again
    other = Message(lead_id=enr.lead_id, enrollment_id=enr.id, channel="email", direction="out", to_addr="x@y.example.test", status="unconfirmed", blocked_reason="send_unconfirmed" + STEP_COUNTED, created_at=NOW)
    session.add(other)
    session.commit()
    enr.current_step = 1
    assert mark_not_sent(session, other.id, decided_by="owner", now=NOW + timedelta(days=3)) == "paused" and enr.current_step == 0


# ---------------------------------------------------------------- MEDIUM 4. a refusing relay, a failure after acceptance, no endless retries

def one_enrollment(session) -> Enrollment:
    """Pause every enrolment but one lead in New York (it is 12:00 there at NOW), so one tick sends exactly one message."""
    from pipecairn.models import Contact

    rows = list(session.scalars(select(Enrollment).join(Lead, Enrollment.lead_id == Lead.id).join(Contact, Lead.contact_id == Contact.id).where(Contact.timezone == "America/New_York").order_by(Enrollment.id)))
    chosen = rows[0]
    for e in session.scalars(select(Enrollment)):
        if e.id != chosen.id:
            e.status = "paused"
    session.commit()
    return chosen


@pytest.fixture
def relay(session, tmp_path, seeded):
    """The real SMTP adapter against the fake server. Only one lead is left in the sequence."""
    prepare(session)
    enr = one_enrollment(session)
    with FakeMailServers() as srv:
        s = mail_settings(tmp_path, srv)
        adapters = Adapters(s)
        adapters.email = SmtpImapEmail(s)
        yield {"srv": srv, "adapters": adapters, "enr": enr, "settings": s, "to": enr.lead.contact.email}


def tick(session, relay, minutes=0):
    r = send_tick(session, relay["settings"], relay["adapters"], NOW + timedelta(minutes=minutes))
    session.commit()
    session.expire_all()
    return r


def test_a_relay_that_refuses_the_address_for_good_is_a_hard_bounce(session, relay):
    relay["srv"].store.refuse_rcpt[relay["to"]] = 550
    tick(session, relay)
    enr = session.get(Enrollment, relay["enr"].id)
    assert suppression_reason(session, email=relay["to"]) == "suppressed_email"
    assert enr.status == "stopped" and enr.stop_reason == "recipient_refused" and enr.lead.status == "dead"
    mb = session.get(Mailbox, session.scalars(select(Message).where(Message.enrollment_id == enr.id)).first().mailbox_id)
    assert mb.bounce_count == 1
    tick(session, relay, 120)
    assert relay["srv"].store.outbox == [] and len(list(session.scalars(select(Message).where(Message.enrollment_id == enr.id)))) == 1  # not tried again


def test_a_relay_that_keeps_refusing_the_message_is_tried_three_times_then_stopped(session, relay):
    relay["srv"].store.refuse_rcpt[relay["to"]] = 450
    for hours in range(MAX_SEND_ATTEMPTS + 2):
        tick(session, relay, 60 * hours)
    enr = session.get(Enrollment, relay["enr"].id)
    failed = list(session.scalars(select(Message).where(Message.enrollment_id == enr.id, Message.status == "failed")))
    assert len(failed) == MAX_SEND_ATTEMPTS == 3
    assert enr.status == "stopped" and enr.stop_reason == "send_failed_repeatedly"
    assert not suppression_reason(session, email=relay["to"])  # a temporary refusal says nothing about the address


@pytest.mark.parametrize("how", ["quit_reply", "silent_at_quit"])
def test_an_error_while_closing_the_connection_after_the_server_accepted_the_mail_does_not_mean_failed(how, session, relay, monkeypatch):
    import pipecairn.adapters.smtp_imap as mod

    monkeypatch.setattr(mod, "SMTP_TIMEOUT", 0.5)
    if how == "quit_reply":
        relay["srv"].store.quit_reply = "421 4.4.2 closing connection (timeout)"  # not the 221 that smtplib expects: it raises after the message was accepted
    else:
        relay["srv"].store.silent_at_quit = True
    tick(session, relay)
    assert len(relay["srv"].store.outbox) == 1
    m = session.scalars(select(Message).where(Message.enrollment_id == relay["enr"].id)).one()
    assert m.status == "sent" and m.external_id.startswith("<")
    tick(session, relay, 120)
    assert len(relay["srv"].store.outbox) == 1  # not sent again an hour later


def test_no_answer_after_the_message_was_handed_over_is_unconfirmed_and_never_resent(session, relay, monkeypatch):
    import pipecairn.adapters.smtp_imap as mod

    monkeypatch.setattr(mod, "SMTP_TIMEOUT", 0.5)
    relay["srv"].store.silent_after_data = True
    tick(session, relay)
    m = session.scalars(select(Message).where(Message.enrollment_id == relay["enr"].id)).one()
    assert m.status == "unconfirmed" and m.blocked_reason.startswith("send_unconfirmed") and m.external_id.startswith("<")
    enr = session.get(Enrollment, relay["enr"].id)
    assert enr.current_step == 1 and enr.status == "active"
    relay["srv"].store.silent_after_data = False
    tick(session, relay, 120)
    assert len(relay["srv"].store.outbox) == 1, "the message was sent a second time"


def test_a_broken_connection_or_login_is_retried_but_never_stops_the_lead(session, settings, adapters, seeded):
    class Down(RecordingEmail):
        def send(self, **kw):
            err = AdapterError("The mail server rejected the user name or password.")
            err.message_specific = False
            raise err

    prepare(session)
    one_enrollment(session)
    adapters.email = Down(settings)
    for hours in range(MAX_SEND_ATTEMPTS + 3):
        send_tick(session, settings, adapters, NOW + timedelta(hours=hours))
        session.commit()
    enr = session.scalars(select(Enrollment).where(Enrollment.status == "active")).one()
    assert enr.stop_reason == "" and len(list(session.scalars(select(Message).where(Message.status == "failed")))) > MAX_SEND_ATTEMPTS


# ---------------------------------------------------------------- LOW: the smaller findings

from fastapi.testclient import TestClient  # noqa: E402

from pipecairn import intake  # noqa: E402
from pipecairn.api.app import create_app  # noqa: E402
from support import DATA  # noqa: E402
from test_api import login  # noqa: E402


@pytest.fixture
def client(tmp_path):
    s = make_settings(tmp_path, seed_dir=str(DATA), mode="live", webhook_shared_secret="whsec")
    return TestClient(create_app(s), base_url="http://api.test")


def test_the_login_route_refuses_a_large_body_before_reading_it(client):
    assert client.post("/api/auth/login", content=b"x" * 25_000_000, headers={"content-type": "application/json"}).status_code == 413
    big = {"email": "owner@example.test", "password": "p" * 5000}
    assert client.post("/api/auth/login", json=big).status_code == 413  # stated length over the limit
    assert client.post("/api/auth/login", json={"email": "owner@example.test", "password": "wrong"}).status_code == 401  # a normal sign in is untouched
    assert login(client)["role"] == "owner"
    assert client.post("/api/leads/import", json={"csv": "email\n" + "a@example.test\n" * 1000}).status_code in (200, 422)  # other routes keep the shared limit


def test_csv_headers_are_matched_the_way_people_write_them():
    rows, ignored = intake.parse_csv_report("﻿First Name,Last-Name, E-mail ,Job Title,Company Name,Favourite colour\nAva,Ng,ava@acme.example.test,CEO,Acme,blue\n")
    assert rows == [{"first_name": "Ava", "last_name": "Ng", "email": "ava@acme.example.test", "title": "CEO", "company": "Acme"}]
    assert ignored == ["Favourite colour"]


def test_the_import_result_lists_the_columns_that_were_ignored(client):
    login(client)
    r = client.post("/api/leads/import", json={"csv": "Email,First Name,Mystery\nnew.person@acme.example.test,Ava,x\n"})
    assert r.status_code == 200 and r.json()["created"] == 1 and r.json()["ignored_columns"] == ["Mystery"]


def test_an_oversized_cell_or_an_unreadable_file_is_a_plain_message_not_a_500(client):
    login(client)
    r = client.post("/api/leads/import", json={"csv": "email,first_name\na@acme.example.test," + "x" * 200_000 + "\n"})
    assert r.status_code == 422 and "could not be read" in r.json()["error"]["message"]
    r = client.post("/api/leads/import", json={"csv": "email,first_name\nb@acme.example.test," + "y" * 500 + "\nc@acme.example.test,Ok\n"})
    assert r.status_code == 200 and r.json()["created"] == 1 and r.json()["flagged"]["cell_too_long"] == 1
    r = client.post("/api/leads/import", json={"csv": 'email,first_name\nd@acme.example.test,"never closed\n'})
    assert r.status_code in (200, 422)


def test_an_unmatched_message_can_be_turned_into_a_suppression_with_one_click(client, tmp_path):
    login(client)
    from sqlalchemy.orm import Session

    with Session(client.app.state.ctx.factory.kw["bind"]) as s:
        s.add(UnmatchedMail(external_id="u9", from_addr="Someone.Else@Alias.example.test", subject="Re: hi", snippet="please stop", created_at=NOW))
        s.commit()
    row = client.get("/api/inbox/unmatched").json()[0]
    assert row["flag"] == "" and row["from"] == "Someone.Else@Alias.example.test"
    r = client.post(f"/api/inbox/unmatched/{row['id']}/suppress")
    assert r.status_code == 200
    with Session(client.app.state.ctx.factory.kw["bind"]) as s:
        assert suppression_reason(s, email="someone.else@alias.example.test") == "suppressed_email"
    assert client.get("/api/inbox/unmatched").json() == []
    assert client.post("/api/inbox/unmatched/99999/suppress").status_code == 404


def test_the_latest_event_id_lets_the_live_stream_start_after_the_history(client):
    login(client)
    assert client.post("/api/demo/reset").status_code == 200
    first = client.get("/api/events/latest").json()["id"]
    assert client.post("/api/demo/tick").status_code == 200
    assert client.get("/api/events/latest").json()["id"] > first >= 0


def test_the_web_app_listens_for_every_kind_of_event_the_api_records():
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    kinds = set()
    for f in (root / "apps/api/src").rglob("*.py"):
        kinds |= set(re.findall(r'record_event\(\s*\w+,\s*"([a-z_.]+)"', f.read_text()))
    listed = set(re.findall(r'"([a-z_.]+)"', (root / "apps/web/src/lib/eventKinds.ts").read_text()))
    assert kinds and kinds <= listed, f"events the page does not listen for: {sorted(kinds - listed)}"
    hooks = (root / "apps/web/src/lib/hooks.ts").read_text()
    assert "addEventListener" in hooks and "after=${last}" in hooks and "/events/latest" in hooks


def test_sqlite_gets_a_new_column_at_start_without_losing_data(tmp_path):
    from sqlalchemy import create_engine, inspect, text

    from pipecairn.dbupgrade import create_and_upgrade

    engine = create_engine(f"sqlite:///{tmp_path / 'old.sqlite3'}")
    with engine.begin() as c:  # a database made by the version before this column existed
        c.execute(text("CREATE TABLE cl_unmatched_mail (id INTEGER PRIMARY KEY, external_id VARCHAR(120) NOT NULL, from_addr VARCHAR(254) NOT NULL, to_addr VARCHAR(254) NOT NULL, "
                       "subject VARCHAR(300) NOT NULL, snippet TEXT NOT NULL, handled BOOLEAN NOT NULL, created_at DATETIME NOT NULL)"))
        c.execute(text("INSERT INTO cl_unmatched_mail VALUES (1, 'e', 'a@b.test', 'c@d.test', 's', 'x', 0, '2026-12-01 00:00:00')"))
    assert "cl_unmatched_mail.flag" in create_and_upgrade(engine)
    assert "flag" in {c["name"] for c in inspect(engine).get_columns("cl_unmatched_mail")}
    with engine.connect() as c:
        assert c.execute(text("SELECT flag, from_addr FROM cl_unmatched_mail")).all() == [("", "a@b.test")]
    assert create_and_upgrade(engine) == []  # nothing to do the second time


def test_the_backup_script_writes_files_only_the_owner_can_read():
    import subprocess
    from pathlib import Path

    script = Path(__file__).resolve().parents[3] / "deploy/hetzner/backup.sh"
    text_ = script.read_text()
    assert "umask 077" in text_ and 'chmod 700 "$OUT"' in text_
    assert text_.index("umask 077") < text_.index("pg_dump")
    assert subprocess.run(["sh", "-n", str(script)], capture_output=True).returncode == 0


def test_the_not_sent_route_reopens_an_unconfirmed_step_for_a_person(client):
    from sqlalchemy.orm import Session

    login(client)
    client.post("/api/demo/reset")
    client.post("/api/demo/tick")
    with Session(client.app.state.ctx.factory.kw["bind"]) as s:
        enr = s.scalars(select(Enrollment)).first()
        enr.current_step = 1
        msg = Message(lead_id=enr.lead_id, enrollment_id=enr.id, channel="email", direction="out", to_addr="x@y.example.test", status="unconfirmed", blocked_reason="send_unconfirmed" + STEP_COUNTED, created_at=NOW)
        s.add(msg)
        s.commit()
        mid, eid = msg.id, enr.id
    assert client.post(f"/api/messages/{mid}/not-sent").status_code == 200
    with Session(client.app.state.ctx.factory.kw["bind"]) as s:
        assert s.get(Message, mid).status == "not_sent" and s.get(Enrollment, eid).current_step == 0
    assert client.post(f"/api/messages/{mid}/not-sent").status_code == 409  # only once
    assert client.post("/api/messages/999999/not-sent").status_code == 409


# ---------------------------------------------------------------- more reading of mail, through the real adapter and the real job

def test_a_stop_request_in_html_only_mail_is_read(session, polled, world):  # noqa: F811
    polled.srv.store.deliver(raw_mail(lead_email(world), "<html><body><p>Please <b>remove me</b> from your list.</p><style>p{}</style></body></html>", ctype="text/html; charset=utf-8", msg_id="h1@x.example.test"))
    polled.poll()
    assert suppression_reason(session, email=lead_email(world)) == "suppressed_email"


def test_mail_from_someone_who_is_not_a_lead_is_left_alone_by_default(session, polled, world):  # noqa: F811
    polled.srv.store.deliver(raw_mail("friend@personal.example.test", "Lunch on Friday?", msg_id="p1@x.example.test"))
    out = polled.poll()
    assert out["unmatched"] == 0 and not list(session.scalars(select(UnmatchedMail)))  # nothing copied
    assert polled.seen() == [False]  # and it was not marked as read


def test_with_the_opt_in_such_mail_is_kept_and_marked_read(session, polled, world):  # noqa: F811
    polled.ctx.settings = polled.ctx.settings.model_copy(update={"keep_unmatched_mail": True})
    polled.srv.store.deliver(raw_mail("friend@personal.example.test", "Please stop writing to this address.", msg_id="p2@x.example.test"))
    polled.poll()
    row = session.scalars(select(UnmatchedMail)).one()
    assert row.flag == "" and "stop writing" in row.snippet and polled.seen() == [True]


def test_a_message_that_cannot_be_stored_three_polls_in_a_row_is_kept_as_unreadable_mail(session, polled, world, monkeypatch):  # noqa: F811
    from pipecairn import inbox

    polled.srv.store.deliver(raw_mail(lead_email(world), "hello", msg_id="stuck@x.example.test"))
    polled.srv.store.deliver(raw_mail(lead_email(world), "STOP", msg_id="fine@x.example.test"))
    real = inbox.capture_email

    def refuses_one(s, st, llm, cal, inb, now):
        if "stuck" in inb.external_id:
            raise RuntimeError("the database said no")
        return real(s, st, llm, cal, inb, now)

    monkeypatch.setattr(inbox, "capture_email", refuses_one)
    polled.poll()
    assert polled.seen() == [False, True]  # the stuck one is not marked read, the other one is stored
    with pytest.raises(RuntimeError):
        polled.poll()  # nothing at all could be stored this time: the job fails where the owner can see it
    session.rollback()
    assert polled.seen() == [False, True] and not list(session.scalars(select(UnmatchedMail)))
    polled.poll()  # the third failure
    row = session.scalars(select(UnmatchedMail)).one()
    assert row.flag == "unreadable" and row.snippet == "" and polled.seen() == [True, True]
    assert suppression_reason(session, email=lead_email(world)) == "suppressed_email"  # the stop request behind it was never held up


def test_the_email_webhook_reads_the_action_and_status_a_relay_passes_on(tmp_path, world, session):  # noqa: F811
    import hashlib
    import hmac
    import json

    from pipecairn.api.app import create_app

    c = TestClient(create_app(make_settings(tmp_path, seed_dir=str(DATA), webhook_shared_secret="whsec")), base_url="http://api.test")
    sent_id = our_sent_id(session, world)

    def post(action, status, n):
        body = json.dumps({"from": "mailer-daemon@mx.example.test", "to": "alex@mail.example.test", "subject": "Undelivered", "text": "This is the mail system.", "message_id": f"<w{n}@mx>",
                           "dsn": True, "references": [f"<{sent_id.strip('<>')}>"], "dsn_action": action, "dsn_status": status}).encode()
        return c.post("/api/webhooks/email", content=body, headers={"x-signature": hmac.new(b"whsec", body, hashlib.sha256).hexdigest()})

    assert post("delayed", "4.4.1", 1).status_code == 200
    session.expire_all()
    assert not suppression_reason(session, email=lead_email(world))  # a late notice is ignored
    assert post("failed", "5.1.1", 2).json()["captured"] is True
    session.expire_all()
    assert suppression_reason(session, email=lead_email(world)) == "suppressed_email"


# ---------------------------------------------------------------- FastAPI 0.165 saves a bare Depends(db) AFTER the answer has gone out

def test_every_route_asks_for_its_session_with_the_function_scope():
    import re
    from pathlib import Path

    api = Path(__file__).resolve().parents[1] / "src" / "pipecairn" / "api"
    bare = [f.name for f in api.glob("*.py") if re.search(r"Depends\(db\)", f.read_text())]
    assert bare == []  # `Depends(db)` saves after the answer has gone out, so a failed save still shows success and a webhook sender never retries


def fail_next_commit(factory):
    from sqlalchemy import event

    state = {"on": True}

    def boom(session):
        if state["on"]:
            raise RuntimeError("disk full")

    event.listen(factory, "before_commit", boom)
    return state


def test_a_change_that_cannot_be_saved_is_an_error_not_a_success(client):
    login(client)
    quiet = TestClient(client.app, raise_server_exceptions=False, base_url="http://api.test", headers=dict(client.headers))
    state = fail_next_commit(client.app.state.ctx.factory)
    r = quiet.post("/api/settings", json={"kill_switch": True})
    state["on"] = False
    assert r.status_code == 500  # before the fix the 200 went out first and the save failed afterwards


def test_an_email_webhook_that_cannot_be_saved_is_refused_so_the_sender_sends_it_again(tmp_path):
    import hashlib
    import hmac
    import json

    s = make_settings(tmp_path, seed_dir=str(DATA), webhook_shared_secret="whsec")
    app = create_app(s)
    quiet = TestClient(app, raise_server_exceptions=False, base_url="http://api.test")
    state = fail_next_commit(app.state.ctx.factory)
    body = json.dumps({"from": "someone@example.test", "to": "a@b.example.test", "subject": "x", "text": "STOP", "message_id": "<wf1@x>"}).encode()
    h = {"x-signature": hmac.new(b"whsec", body, hashlib.sha256).hexdigest()}
    assert quiet.post("/api/webhooks/email", content=body, headers=h).status_code == 500
    state["on"] = False
    assert quiet.post("/api/webhooks/email", content=body, headers=h).status_code == 200
