"""Mail: verified TLS, plain text only for this computer, opt out headers and footer, and what a bounce or a stop request has to prove."""

import datetime as dt
import socket
import ssl
import threading

import pytest
from sqlalchemy import select

from support import NOW, make_settings
from mock.mail_servers import StubMailServers
from pipecairn.adapters.base import InboundEmail
from pipecairn.adapters.smtp_imap import SmtpImapEmail, delivery_report_facts
from pipecairn.inbox import capture_email
from pipecairn.models import Mailbox, Message, Reply, Suppression
from pipecairn.unsubscribe import list_unsubscribe_headers, make_token, read_token, unsubscribe_url, with_footer
from sendora_core.adapters import AdapterError
from test_inbox import cap, world  # noqa: F401  (the fixture and helper of the inbox tests)


def tls_server(handle):
    """A one shot TLS server with a self signed certificate, which a verifying client must refuse."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = dt.datetime.now(dt.UTC)
    cert = x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(1).not_valid_before(now - dt.timedelta(days=1)).not_valid_after(now + dt.timedelta(days=1)).sign(key, hashes.SHA256())
    return key, cert, serialization


@pytest.fixture
def self_signed(tmp_path):
    key, cert, ser = tls_server(None)
    (tmp_path / "c.pem").write_bytes(cert.public_bytes(ser.Encoding.PEM))
    (tmp_path / "k.pem").write_bytes(key.private_bytes(ser.Encoding.PEM, ser.PrivateFormat.PKCS8, ser.NoEncryption()))
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(tmp_path / "c.pem", tmp_path / "k.pem")
    return ctx


def serve_once(server_side):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    threading.Thread(target=lambda: (lambda c: server_side(c))(sock.accept()[0]), daemon=True).start()
    return sock.getsockname()[1]


def test_smtp_starttls_refuses_an_unverified_certificate(tmp_path, self_signed):
    def smtp(conn):
        f = conn.makefile("rwb")
        f.write(b"220 hello\r\n"); f.flush()
        f.readline()  # EHLO
        f.write(b"250-hello\r\n250 STARTTLS\r\n"); f.flush()
        f.readline()  # STARTTLS
        f.write(b"220 go ahead\r\n"); f.flush()
        try:
            self_signed.wrap_socket(conn, server_side=True)
        except (ssl.SSLError, OSError):
            pass  # the client walked away, which is the point

    port = serve_once(smtp)
    a = SmtpImapEmail(make_settings(tmp_path, smtp_host="127.0.0.1", smtp_port=port, smtp_use_tls=True, smtp_user="u", smtp_password="p"))
    with pytest.raises(AdapterError) as e:
        a.send(from_addr="a@b.example.test", to="c@d.example.test", subject="s", body="b")
    assert "certificate" in str(e.value)
    ok, detail = a.healthcheck()
    assert not ok


def test_imap_ssl_refuses_an_unverified_certificate(tmp_path, self_signed):
    def imap(conn):
        try:
            self_signed.wrap_socket(conn, server_side=True)
        except (ssl.SSLError, OSError):
            pass

    port = serve_once(imap)
    a = SmtpImapEmail(make_settings(tmp_path, imap_host="127.0.0.1", imap_port=port, imap_use_ssl=True, smtp_host="127.0.0.1", smtp_user="u", smtp_password="p"))
    with pytest.raises(AdapterError) as e:
        a.fetch_replies()
    assert "certificate" in str(e.value)


def test_plain_text_mail_is_refused_for_any_host_but_this_computer(tmp_path):
    a = SmtpImapEmail(make_settings(tmp_path, smtp_host="mail.provider.example.test", smtp_use_tls=False, imap_host="imap.provider.example.test", imap_use_ssl=False, smtp_user="u", smtp_password="p"))
    with pytest.raises(AdapterError) as e:
        a.send(from_addr="a@b.example.test", to="c@d.example.test", subject="s", body="b")
    assert "same computer" in str(e.value)
    with pytest.raises(AdapterError) as e:
        a.fetch_replies()
    assert "same computer" in str(e.value)


def test_outgoing_mail_carries_the_opt_out_headers_and_reply_to(tmp_path):
    with StubMailServers() as srv:
        s = make_settings(tmp_path, smtp_host=srv.host, smtp_port=srv.smtp_port, smtp_use_tls=False, smtp_user="demo", smtp_password="demo-password", reply_to="sam@rivera.example.test",
                          public_base_url="https://api.rivera.example.test", session_secret="test-only-session-secret-for-unsubscribe-1")
        SmtpImapEmail(s).send(from_addr="sam@rivera.example.test", to="ava@acme.example.test", subject="Hi", body="Hello")
        head = srv.store.outbox[0]["data"].split("\r\n\r\n")[0].replace("\r\n ", " ").replace("\r\n\t", " ")  # long headers are folded
    assert "Reply-To: sam@rivera.example.test" in head
    assert "List-Unsubscribe: <mailto:sam@rivera.example.test?subject=unsubscribe>, <https://api.rivera.example.test/api/webhooks/unsubscribe/" in head
    assert "List-Unsubscribe-Post: List-Unsubscribe=One-Click" in head


def test_without_a_public_url_only_the_mailto_header_is_added(tmp_path):
    s = make_settings(tmp_path)
    h = list_unsubscribe_headers(s, "sam@rivera.example.test", "ava@acme.example.test")
    assert h == {"List-Unsubscribe": "<mailto:sam@rivera.example.test?subject=unsubscribe>"}


def test_the_unsubscribe_token_is_signed(tmp_path):
    t = make_token("test-only-secret-one", "Ava@Acme.example.test")
    assert read_token("test-only-secret-one", t) == "ava@acme.example.test"
    assert read_token("test-only-secret-two", t) is None
    assert read_token("test-only-secret-one", t[:-2] + "xx") is None and read_token("x", "garbage") is None
    assert unsubscribe_url(make_settings(tmp_path, public_base_url="http://plain.example.test"), "a@b.example.test") == ""  # https only


def test_the_footer_names_the_company_gives_the_address_and_says_how_to_stop(tmp_path):
    s = make_settings(tmp_path, company_name="Rivera Works", company_address="12 Main Street, Springfield, IL 62701, USA")
    out = with_footer(s, "email", "Hi Ava,\n\nA short note.\n")
    assert out.endswith("Rivera Works\n12 Main Street, Springfield, IL 62701, USA\nReply STOP to opt out of these emails.")
    again = with_footer(s, "email", out)
    assert again == out  # nothing is added twice
    assert with_footer(s, "sms", "Hi Ava, quick note") == "Hi Ava, quick note Reply STOP to opt out."
    assert with_footer(s, "sms", "Hi. Reply STOP to opt out.") == "Hi. Reply STOP to opt out."
    assert "unsubscribe" in with_footer(s, "email", "Click to unsubscribe").lower() and "Reply STOP" not in with_footer(s, "email", "Click to unsubscribe")


def test_a_delivery_report_is_recognised_by_its_shape_and_names_our_message_id(tmp_path):
    raw = (b"From: MAILER-DAEMON@mx.example.test\r\nTo: sam@rivera.example.test\r\nSubject: Undelivered\r\nAuthentication-Results: mx; spf=pass\r\nMIME-Version: 1.0\r\n"
           b"Content-Type: multipart/report; report-type=delivery-status; boundary=B\r\n\r\n--B\r\nContent-Type: text/plain\r\n\r\nCould not deliver.\r\n"
           b"--B\r\nContent-Type: message/delivery-status\r\n\r\nFinal-Recipient: rfc822; ava@acme.example.test\r\nAction: failed\r\nStatus: 5.1.1\r\n\r\n"
           b"--B\r\nContent-Type: text/rfc822-headers\r\n\r\nMessage-ID: <sent-1@rivera.example.test>\r\nSubject: Hi\r\n\r\n--B--\r\n")
    with StubMailServers() as srv:
        srv.store.deliver(raw)
        srv.store.deliver(b"From: MAILER-DAEMON@evil.example.test\r\nTo: sam@rivera.example.test\r\nSubject: Mail delivery failed\r\nMessage-ID: <x@evil>\r\n\r\nMail delivery failed. 550 5.1.1 User unknown for ava@acme.example.test\r\n")
        s = make_settings(tmp_path, smtp_host=srv.host, imap_host=srv.host, imap_port=srv.imap_port, imap_use_ssl=False, smtp_user="demo", smtp_password="demo-password")
        got = SmtpImapEmail(s).fetch_replies()
    real, forged = got
    assert real.is_dsn and real.references == ("<sent-1@rivera.example.test>",) and "spf=pass" in real.auth_results
    assert not forged.is_dsn and forged.references == ()
    import email
    from email.policy import default

    assert delivery_report_facts(email.message_from_bytes(raw, policy=default))[0] is True


def forged_bounce(world, **kw):  # noqa: F811
    return InboundEmail(external_id="forged-1", from_addr="mailer-daemon@evil.example.test", to_addr="sam@x.test", subject="Mail delivery failed",
                        body=f"Delivery Status Notification (Failure). 550 5.1.1 User unknown: {world['lead'].contact.email}", **kw)


def test_a_forged_bounce_changes_nothing(session, world):  # noqa: F811
    lead, before = world["lead"], None
    mb = session.scalars(select(Mailbox)).first()
    before = (mb.bounce_count, lead.status)
    # from the lead's own address, plain text: the words are not proof
    r = cap(session, world, "Delivery Status Notification (Failure). 550 5.1.1 User unknown.", ext="plain-1")
    assert r.intent == "bounce" and r.suggested_action == "unverified_bounce" and not r.handled  # kept open: a person reads it
    # from a sample mail system address: the old code looked the lead up from the address written in the text
    assert capture_email(session, world["settings"], world["llm"], world["adapters"].calendar, forged_bounce(world), NOW) is None
    # a report shaped like a real one but naming a message we never sent
    assert capture_email(session, world["settings"], world["llm"], world["adapters"].calendar, forged_bounce(world, is_dsn=True, references=("<not-ours@x>",)), NOW) is None
    session.commit()
    assert (mb.bounce_count, lead.status) == before
    assert session.scalars(select(Suppression).where(Suppression.value == lead.contact.email)).first() is None


def test_a_real_delivery_report_is_found_by_the_message_id_not_the_sender(session, world):  # noqa: F811
    sent = session.scalars(select(Message).where(Message.lead_id == world["lead"].id, Message.status == "sent")).first()
    ref = "<" + sent.external_id.strip("<>").upper() + ">"  # case and brackets do not matter
    r = capture_email(session, world["settings"], world["llm"], world["adapters"].calendar, forged_bounce(world, is_dsn=True, references=(ref,)), NOW)
    session.commit()
    assert r is not None and r.intent == "bounce" and r.suggested_action == "suppressed" and world["lead"].status == "dead"


def test_a_stop_request_still_acts_at_once_and_leaves_an_audit_note(session, world):  # noqa: F811
    from sendora_core.models import AuditEntry

    r = cap(session, world, "Please remove me from your list.", ext="stop-1", auth_results="mx; spf=fail")
    assert r.intent == "unsubscribe" and world["lead"].status == "suppressed"
    note = [e for e in session.scalars(select(AuditEntry)) if e.action == "suppression.from_reply"]
    assert note and "spf=fail" in str(note[-1].detail)


def test_a_message_without_an_id_is_stored_once(session, world):  # noqa: F811
    first = cap(session, world, "Yes please send a proposal", ext="")
    assert first is not None and cap(session, world, "Yes please send a proposal", ext="") is None
    assert len(list(session.scalars(select(Reply)))) == 1


FOOTER = "\n\n--\nRivera Works\n12 Main Street, Springfield, IL 62701, USA\nReply STOP to opt out of these emails."
OURS = "Hi Ava,\n\nI help dental teams answer enquiries within minutes. Would a short call be useful?\n\nBest,\nSam" + FOOTER


@pytest.mark.parametrize("reply", [
    "Yes, this sounds useful. Can we talk Thursday?\n\nOn Tue, Dec 1, 2026 at 5:00 PM Sam <sam@rivera.example.test> wrote:\n" + "\n".join("> " + ln for ln in OURS.splitlines()),
    "Yes please send times.\n\nFrom: Sam <sam@rivera.example.test>\nSent: Tuesday, December 1, 2026 5:00 PM\nTo: Ava\nSubject: Quick idea\n\n" + OURS,
    "Interested, call me.\n\n" + OURS,
    "Sounds good, let's talk\n\nReply STOP to opt out of these emails.",
    "Sounds good, let's talk. Reply STOP to opt out.",
], ids=["gmail_quote", "outlook_quote", "pasted_below", "footer_line_alone", "sms_footer_alone"])
def test_the_footer_we_add_is_never_read_back_as_a_request_to_stop(reply):
    from pipecairn.replies import classify_reply

    assert classify_reply(reply, None).intent != "unsubscribe"


def test_a_real_stop_is_still_a_stop_with_the_footer_quoted():
    from pipecairn.replies import classify_reply

    assert classify_reply("Please stop emailing me.\n\n> " + OURS.replace("\n", "\n> "), None).intent == "unsubscribe"
    assert classify_reply("STOP", None).intent == "unsubscribe"
