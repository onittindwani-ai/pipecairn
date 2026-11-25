"""Reading one raw email into an InboundEmail, however badly it is made.

Anyone on the internet can send mail to the inbox, so a message may have a character set that does not exist, broken base64, a gigantic header, thousands of
nested parts or no parts at all. None of that may stop the other messages from being read, and a request to stop inside such a message must still be seen.
So: a message is read in two steps. The first reads it properly and decodes every part on its own (a bad part is decoded with replacement characters and the
message is flagged). If even that fails, the second step keeps the raw bytes as text and takes the sender, subject and message ids from the header lines with
plain patterns. Either way a message comes out, never an exception.
"""

from __future__ import annotations

import codecs
import email
import html
import re
from email.header import decode_header, make_header
from email.policy import default as default_policy
from email.utils import parseaddr

from pipecairn.adapters.base import InboundEmail

TEXT_LIMIT = 20_000
HEADER_LIMIT = 50_000  # bytes of the header block read by the fallback
MESSAGE_ID = re.compile(r"<[^<>\s]+>")
HEADER_ID = re.compile(r"^message-id:\s*(<[^<>\s]+>)", re.I | re.M)
TAGS = re.compile(r"<(script|style)\b.*?</\1>|<[^>]{0,2000}>", re.I | re.S)
STATUS_CODE = re.compile(r"\b([245])\.\d{1,3}\.\d{1,3}\b")


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
                ids += HEADER_ID.findall(_payload_text(part)[0])
    return is_dsn, tuple(dict.fromkeys(ids))[:20]


def delivery_status_of(msg) -> tuple[str, str]:
    """(Action, Status) as the report states them, for example ("failed", "5.1.1") or ("delayed", "4.4.1"). A report names one group per recipient; a permanent
    failure in any group decides, otherwise the first group that has an Action. ("", "") when there is none."""
    groups: list[tuple[str, str]] = []
    for part in msg.walk():
        if part.get_content_type() != "message/delivery-status":
            continue
        payload = part.get_payload()
        for grp in payload if isinstance(payload, list) else []:
            action = str(grp.get("Action") or "").strip().lower().split()[0:1]
            status = STATUS_CODE.search(str(grp.get("Status") or ""))
            if action:
                groups.append((action[0], status.group(0) if status else ""))
    for action, status in groups:
        if action == "failed" and status.startswith("5"):
            return action, status
    return groups[0] if groups else ("", "")


def _payload_text(part) -> tuple[str, str]:
    """(text, note) of one part when the normal decoding failed: the bytes are decoded with replacement characters, with the declared character set when it exists."""
    try:
        raw = part.get_payload(decode=True) or b""
    except Exception:  # a payload that cannot even be transfer decoded
        raw = str(part.get_payload() or "").encode("utf-8", "replace")
    charset = (part.get_content_charset() or "").strip()
    note = ""
    if charset:
        try:
            codecs.lookup(charset)
        except LookupError:
            charset, note = "", f"unknown charset {charset[:40]}"
    return raw.decode(charset or "utf-8", "replace"), note


def _part_text(part) -> tuple[str, str]:
    try:
        text = part.get_content()
        return (text if isinstance(text, str) else str(text)), ""
    except Exception:  # unknown character set, bad bytes, bad transfer encoding: whatever it is, decode it ourselves
        text, note = _payload_text(part)
        return text, note or "part could not be decoded cleanly"


def _body_text(msg) -> tuple[str, str]:
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return "", ""
    text, note = _part_text(part)
    if part.get_content_type() == "text/html":
        text = html.unescape(TAGS.sub(" ", text))
    return text, note


def parse_inbound(uid: str, raw: bytes) -> InboundEmail:
    """One raw message to an InboundEmail. Never raises."""
    try:
        return _parse(uid, raw)
    except Exception as exc:  # RecursionError on deeply nested parts, header errors, anything: the message is kept
        return _salvage(uid, raw, type(exc).__name__)


def _parse(uid: str, raw: bytes) -> InboundEmail:
    msg = email.message_from_bytes(raw, policy=default_policy)
    text, note = _body_text(msg)
    is_dsn, refs = delivery_report_facts(msg)
    action, status = delivery_status_of(msg) if is_dsn else ("", "")
    return InboundEmail(
        external_id=str(msg["Message-ID"] or f"imap-{uid}"), from_addr=parseaddr(str(msg["From"] or ""))[1], to_addr=parseaddr(str(msg["To"] or ""))[1],
        subject=str(msg["Subject"] or ""), body=text[:TEXT_LIMIT], is_dsn=is_dsn, references=refs, auth_results=str(msg["Authentication-Results"] or "")[:300], uid=uid,
        dsn_action=action, dsn_status=status, parse_problem=f"parse: {note}"[:120] if note else "",
    )


def _header(block: str, name: str) -> str:
    m = re.search(rf"^{name}:[ \t]*(.*(?:\r?\n[ \t]+.*)*)", block, re.I | re.M)
    return re.sub(r"\s*\r?\n\s*", " ", m.group(1)).strip() if m else ""


def _decoded(value: str) -> str:
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _salvage(uid: str, raw: bytes, why: str) -> InboundEmail:
    """The whole message as text, flagged. Sender, subject and the ids it answers come from the header lines; the body is everything after them, decoded loosely."""
    parts = re.split(rb"\r?\n\r?\n", raw, maxsplit=1)
    block = parts[0][:HEADER_LIMIT].decode("utf-8", "replace")
    body = (parts[1] if len(parts) > 1 else b"")[: TEXT_LIMIT * 4].decode("utf-8", "replace").replace("\x00", "")
    refs = tuple(dict.fromkeys(MESSAGE_ID.findall(_header(block, "In-Reply-To")) + MESSAGE_ID.findall(_header(block, "References"))))[:20]
    mid = MESSAGE_ID.search(_header(block, "Message-ID"))
    return InboundEmail(
        external_id=mid.group(0) if mid else f"imap-{uid}", from_addr=parseaddr(_header(block, "From"))[1], to_addr=parseaddr(_header(block, "To"))[1],
        subject=_decoded(_header(block, "Subject"))[:300], body=body[:TEXT_LIMIT], references=refs, uid=uid, parse_problem=f"parse: unreadable ({why})"[:120], unreadable=True,
    )
