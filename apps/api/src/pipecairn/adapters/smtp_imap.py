"""Email over SMTP (send) and IMAP (read replies). Works with Gmail (app password), Outlook and most mail hosts."""

from __future__ import annotations

import email
import imaplib
import ipaddress
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.policy import default as default_policy
from email.utils import make_msgid, parseaddr

from pipecairn.adapters.base import InboundEmail
from pipecairn.unsubscribe import list_unsubscribe_headers
from pipecairn.util import clean_header
from sendora_core.adapters import AdapterError
from sendora_core.safety import write_action
from sendora_core.settings import BaseAppSettings


MESSAGE_ID = re.compile(r"<[^<>\s]+>")
HEADER_ID = re.compile(r"^message-id:\s*(<[^<>\s]+>)", re.I | re.M)


def is_loopback(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def delivery_report_facts(msg) -> tuple[bool, tuple[str, ...]]:
    """(is a delivery status report, the Message-IDs it names). A bounce is believed only when it has this shape and names one of our messages."""
    is_dsn = msg.get_content_type() == "multipart/report" and str(msg.get_param("report-type") or "").lower() == "delivery-status"
    ids: list[str] = []
    for header in ("In-Reply-To", "References"):
        ids += MESSAGE_ID.findall(str(msg[header] or ""))
    for part in msg.walk():
        kind = part.get_content_type()
        if kind == "message/rfc822":
            inner = part.get_payload()
            inner = inner[0] if isinstance(inner, list) and inner else None
            if inner is not None and inner["Message-ID"]:
                ids += MESSAGE_ID.findall(str(inner["Message-ID"]))
        elif kind == "text/rfc822-headers":
            try:
                ids += HEADER_ID.findall(part.get_content())
            except (LookupError, ValueError):
                pass
    return is_dsn, tuple(dict.fromkeys(ids))[:20]


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
            c = smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=20, context=ctx)
        else:
            if not s.smtp_use_tls and not is_loopback(s.smtp_host):
                raise AdapterError("SMTP_USE_TLS=false is only allowed for a mail server on this same computer (127.0.0.1). Turn it back on.")
            c = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=20)
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
            with self._smtp() as c:
                c.send_message(m)
        except smtplib.SMTPAuthenticationError as exc:
            raise AdapterError("The mail server rejected the user name or password. For Gmail use an app password.") from exc
        except ssl.SSLCertVerificationError as exc:
            raise AdapterError(f"The certificate of {self.settings.smtp_host} could not be verified, so nothing was sent. Check SMTP_HOST and the port.") from exc
        except (smtplib.SMTPException, OSError) as exc:
            raise AdapterError(f"Could not send through {self.settings.smtp_host}: {type(exc).__name__}.") from exc
        return m["Message-ID"]

    def fetch_replies(self) -> list[InboundEmail]:
        self._need("imap_host", "smtp_user")
        out: list[InboundEmail] = []
        try:
            c = self._imap()
            try:
                c.select("INBOX")
                _, data = c.uid("SEARCH", None, "UNSEEN")
                for uid in (data[0] or b"").split():
                    _, parts = c.uid("FETCH", uid.decode(), "(RFC822)")
                    if not parts or not parts[0]:
                        continue
                    msg = email.message_from_bytes(parts[0][1], policy=default_policy)
                    body_part = msg.get_body(preferencelist=("plain",))
                    text = body_part.get_content() if body_part else ""
                    is_dsn, refs = delivery_report_facts(msg)
                    out.append(InboundEmail(external_id=str(msg["Message-ID"] or f"imap-{uid.decode()}"), from_addr=parseaddr(str(msg["From"] or ""))[1],
                                            to_addr=parseaddr(str(msg["To"] or ""))[1], subject=str(msg["Subject"] or ""), body=text[:20000],
                                            is_dsn=is_dsn, references=refs, auth_results=str(msg["Authentication-Results"] or "")[:300]))
                    c.uid("STORE", uid.decode(), "+FLAGS", "(\\Seen)")
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
