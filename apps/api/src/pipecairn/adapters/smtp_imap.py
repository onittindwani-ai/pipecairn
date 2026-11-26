"""Email over SMTP (send) and IMAP (read replies). Works with Gmail (app password), Outlook and most mail hosts."""

from __future__ import annotations

import imaplib
import ipaddress
import logging
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.policy import default as default_policy
from email.utils import make_msgid

from pipecairn.adapters.base import InboundEmail, RecipientRefused, SendUnconfirmed
from pipecairn.adapters.mailparse import MAX_RAW_BYTES, delivery_report_facts, parse_inbound  # noqa: F401  (delivery_report_facts is re-exported)
from pipecairn.unsubscribe import list_unsubscribe_headers
from pipecairn.util import clean_header
from sendora_core.adapters import AdapterError
from sendora_core.safety import write_action
from sendora_core.settings import BaseAppSettings


log = logging.getLogger("pipecairn.mail")
SMTP_TIMEOUT = 20  # seconds the mail server may take to answer one command


def _problem(text: str, *, message_specific: bool = False) -> AdapterError:
    """An AdapterError that says whether the fault is in this one message (the server refused its content or address for now) or in the connection, the login or
    the certificate. Only the first kind counts toward the limit of tries per step."""
    err = AdapterError(text)
    err.message_specific = message_specific  # type: ignore[attr-defined]
    return err


ENHANCED_CODE = re.compile(r"\b([245])\.(\d{1,3})\.(\d{1,3})\b")
POLICY_WORDS = re.compile(r"\b(?:relay|relaying|denied|blocked|blacklist\w*|blocklist\w*|spam\w*|policy|reputation|rbl|dnsbl|not permitted|not allowed to|forbidden|greylist\w*|too many|rate limit\w*)\b", re.I)
FETCH_SIZE = re.compile(rb"RFC822\.SIZE (\d+)")


def refusal_kind(code: int, text: str) -> str:
    """What a refusal at RCPT TO means: "bad_address" (the mailbox does not exist: suppress the address, count a bounce) or "policy" (the server or its rules said no: a
    blocked sending address, a relay rule, a spam list, a full or disabled mailbox, a busy server. Nothing is wrong with the address, so nothing is suppressed).
    The enhanced status code decides when there is one (5.1.x is a bad address, anything else is not); without one, only 550, 551 and 553 count, and not when the text
    talks about relaying, blocking or policy."""
    m = ENHANCED_CODE.search(text or "")
    if m:
        return "bad_address" if m.group(1) == "5" and m.group(2) == "1" else "policy"
    return "bad_address" if code in {550, 551, 553} and not POLICY_WORDS.search(text or "") else "policy"


def _reply_text(raw) -> str:
    return raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw or "")


def is_loopback(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


class SmtpImapEmail:
    def __init__(self, settings):
        self.settings: BaseAppSettings = settings

    def _need(self, *names: str) -> None:
        missing = [n.upper() for n in names if not getattr(self.settings, n)]
        if missing:
            raise AdapterError(f"Set {', '.join(missing)} in your environment first (see docs/04-ENVIRONMENT-VARIABLES.md).")

    def _smtp(self) -> smtplib.SMTP:
        """Always a verified connection: the certificate and the host name are checked. Plain text is allowed only to this same computer."""
        s = self.settings
        ctx = ssl.create_default_context()
        if s.smtp_port == 465:
            c = smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=SMTP_TIMEOUT, context=ctx)
        else:
            if not s.smtp_use_tls and not is_loopback(s.smtp_host):
                raise AdapterError("SMTP_USE_TLS=false is only allowed for a mail server on this same computer (127.0.0.1). Turn it back on.")
            c = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=SMTP_TIMEOUT)
            if s.smtp_use_tls:
                try:
                    c.starttls(context=ctx)
                except Exception:
                    c.close()
                    raise
        if s.smtp_user:
            c.login(s.smtp_user, s.smtp_password)
        return c

    def _imap(self) -> imaplib.IMAP4:
        s = self.settings
        if s.imap_use_ssl:
            c = imaplib.IMAP4_SSL(s.imap_host, s.imap_port, ssl_context=ssl.create_default_context(), timeout=20)
        elif is_loopback(s.imap_host):
            c = imaplib.IMAP4(s.imap_host, s.imap_port, timeout=20)
        else:
            raise AdapterError("IMAP_USE_SSL=false is only allowed for a mail server on this same computer (127.0.0.1). Turn it back on.")
        c.login(s.smtp_user, s.smtp_password)
        return c

    @staticmethod
    def _close(c: smtplib.SMTP) -> None:
        try:
            c.quit()
        except Exception:
            pass
        try:
            c.close()
        except Exception:
            pass

    @staticmethod
    def _transmit(c: smtplib.SMTP, m: EmailMessage) -> None:
        """Hand the message over. Once the server has been asked to take the message body (DATA), an error that is not a plain refusal means we cannot know
        whether it was accepted, so it is reported as unconfirmed and the message is never sent again."""
        data_started: list[bool] = []
        real_data = c.data

        def data(msg):
            data_started.append(True)
            return real_data(msg)

        c.data = data  # type: ignore[method-assign]
        try:
            c.send_message(m)
        except (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused, smtplib.SMTPDataError, smtplib.SMTPAuthenticationError):
            raise  # the server answered, and the answer was no
        except (smtplib.SMTPException, OSError) as exc:
            if data_started:
                raise SendUnconfirmed(f"The connection failed after the message was sent ({type(exc).__name__}), so it may have been accepted.") from exc
            raise

    @write_action("email.send")
    def send(self, *, from_addr: str, to: str, subject: str, body: str) -> str:
        self._need("smtp_host")
        # 998 is the longest line the mail standard allows. With the default 78 the long unsubscribe link would be rewritten as an encoded word that mail programs cannot read.
        m = EmailMessage(policy=default_policy.clone(max_line_length=998))
        m["From"], m["To"], m["Subject"] = clean_header(from_addr), clean_header(to), clean_header(subject)
        m["Message-ID"] = make_msgid(domain=from_addr.rsplit("@", 1)[-1] or "localhost")
        if getattr(self.settings, "reply_to", ""):
            m["Reply-To"] = clean_header(self.settings.reply_to)
        for name, value in list_unsubscribe_headers(self.settings, clean_header(from_addr), clean_header(to)).items():
            m[name] = value
        m.set_content(body)
        try:
            c = self._smtp()
            try:
                self._transmit(c, m)
            finally:
                self._close(c)  # an error while closing a connection that already accepted the message must never turn a sent message into a failed one
        except (RecipientRefused, SendUnconfirmed) as exc:
            exc.external_id = m["Message-ID"]  # type: ignore[attr-defined]  # a later delivery report can still be matched to this message
            raise
        except smtplib.SMTPRecipientsRefused as exc:
            replies = [(code, _reply_text(text)) for code, text in exc.recipients.values()]
            if replies and all(500 <= code < 600 and refusal_kind(code, text) == "bad_address" for code, text in replies):
                err = RecipientRefused(f"The mail server refused the address for good (code {replies[0][0]}).")
                err.external_id = m["Message-ID"]  # type: ignore[attr-defined]
                raise err from exc
            code = replies[0][0] if replies else "unknown"
            if replies and all(500 <= c < 600 for c, _ in replies):
                # A refusal that is not about the address: a blocked sending address or host, a relay rule, a spam list. It is the mail server's or the mailbox's problem, so
                # it is tried again later, it never counts toward the limit of tries for the lead, and the audit log gets a note for the mailbox.
                err = _problem(f"The mail server refused the message for a reason that is not the address (code {code}). Check the mailbox, its host and your sending reputation. It will be tried again later.")
                err.policy_refusal = code  # type: ignore[attr-defined]
                raise err from exc
            raise _problem(f"The mail server refused the address for now (code {code}). It will be tried again later.", message_specific=True) from exc
        except smtplib.SMTPDataError as exc:
            raise _problem(f"The mail server refused the message (code {exc.smtp_code}).", message_specific=True) from exc
        except smtplib.SMTPAuthenticationError as exc:
            raise _problem("The mail server rejected the user name or password. For Gmail use an app password.") from exc
        except ssl.SSLCertVerificationError as exc:
            raise _problem(f"The certificate of {self.settings.smtp_host} could not be verified, so nothing was sent. Check SMTP_HOST and the port.") from exc
        except (smtplib.SMTPException, OSError) as exc:
            raise _problem(f"Could not send through {self.settings.smtp_host}: {type(exc).__name__}.") from exc
        return m["Message-ID"]

    @staticmethod
    def _fetch_one(c: imaplib.IMAP4, uid: str) -> tuple[bytes, int | None] | None:
        """(the first MAX_RAW_BYTES of the raw message, its full size when the server says it), or None when the server has nothing for it or refuses this one fetch (the
        others are still read). Only the first part is asked for, so a message of many megabytes costs one small read."""
        try:
            _, parts = c.uid("FETCH", uid, f"(RFC822.SIZE BODY.PEEK[]<0.{MAX_RAW_BYTES}>)")
        except imaplib.IMAP4.error:
            log.warning("the mail server refused to give message %s; the others are still read", uid)
            return None
        size = None
        for part in parts or []:
            head = part[0] if isinstance(part, tuple) else part
            found = FETCH_SIZE.search(head) if isinstance(head, bytes) else None
            if found:
                size = int(found.group(1))
        for part in parts or []:
            if isinstance(part, tuple) and len(part) > 1 and isinstance(part[1], bytes):
                return part[1][:MAX_RAW_BYTES], size
        return None

    def fetch_replies(self) -> list[InboundEmail]:
        """Unread messages, read with BODY.PEEK so the mailbox does NOT mark them read. The caller stores each one and only then calls mark_seen:
        a failure part way through leaves the unstored ones unread, so they come again at the next poll (a stored one is recognised and skipped)."""
        self._need("imap_host", "smtp_user")
        out: list[InboundEmail] = []
        try:
            c = self._imap()
            try:
                c.select("INBOX")
                _, data = c.uid("SEARCH", None, "UNSEEN")
                for uid in (data[0] or b"").split():
                    got = self._fetch_one(c, uid.decode())
                    if got is not None:
                        out.append(parse_inbound(uid.decode(), got[0], got[1]))  # never raises: a message that cannot be read is kept as raw text and flagged
            finally:
                try:
                    c.logout()
                except Exception:
                    pass
        except imaplib.IMAP4.error as exc:
            raise AdapterError("The inbox rejected the login or the command. Check the user name and app password.") from exc
        except ssl.SSLCertVerificationError as exc:
            raise AdapterError(f"The certificate of {self.settings.imap_host} could not be verified, so the inbox was not read. Check IMAP_HOST and the port.") from exc
        except OSError as exc:
            raise AdapterError(f"Could not reach the inbox at {self.settings.imap_host}: {type(exc).__name__}.") from exc
        return out

    def mark_seen(self, uids: list[str]) -> None:
        """Mark messages as read once they are stored. A failure here is harmless: the message is fetched again and recognised as already stored."""
        if not uids:
            return
        self._need("imap_host", "smtp_user")
        try:
            c = self._imap()
            try:
                c.select("INBOX")
                for uid in uids:
                    c.uid("STORE", uid, "+FLAGS", "(\\Seen)")
            finally:
                try:
                    c.logout()
                except Exception:
                    pass
        except (imaplib.IMAP4.error, ssl.SSLCertVerificationError, OSError) as exc:
            raise AdapterError(f"Could not mark mail as read at {self.settings.imap_host}: {type(exc).__name__}.") from exc

    def healthcheck(self) -> tuple[bool, str]:
        try:
            self._need("smtp_host", "imap_host")
            with self._smtp() as c:
                c.noop()
            c = self._imap()
            c.logout()
            return True, "Connected to the mail server and the inbox."
        except AdapterError as exc:
            return False, str(exc)
        except Exception as exc:
            return False, f"Could not connect: {type(exc).__name__}. Check host, port and password."
