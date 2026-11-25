"""Reading one raw email into an InboundEmail, however badly it is made.

Anyone on the internet can send mail to the inbox, so a message may have a character set that does not exist, broken base64, a gigantic header, thousands of
nested parts or no parts at all. None of that may stop the other messages from being read, and a request to stop inside such a message must still be seen.
So: a message is read in two steps. The first reads it properly and decodes every part on its own (a bad part is decoded with replacement characters and the
message is flagged). If even that fails, the second step keeps the raw bytes as text and takes the sender, subject and message ids from the header lines with
plain patterns. Either way a message comes out, never an exception.

Limits, because the sender is anyone on the internet and one message is read again at every poll until it is stored or marked read:
- only the first MAX_RAW_BYTES (256 KB) of a message are read; a bigger one is read from its first part and flagged ("large message");
- every header value is cut to HEADER_VALUE_LIMIT characters before the standard library parses it (its address parser is quadratic on long quoted headers);
- tags are stripped by a scanner that never goes back over text it has seen (the old pattern took minutes on a megabyte of "<script ");
- the whole parse has a time limit (PARSE_SECONDS). It uses SIGALRM, so it works in the worker, which runs jobs on its main thread; where it cannot be set (another
  thread, Windows) the size limits and the linear scanner are what protect the reader. A message that takes too long is kept as raw text and flagged unreadable.
"""

from __future__ import annotations

import codecs
import dataclasses
import email
import html
import re
import signal
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from email.header import decode_header, make_header
from email.policy import default as default_policy
from email.utils import parseaddr

from pipecairn.adapters.base import InboundEmail

TEXT_LIMIT = 20_000
HEADER_LIMIT = 50_000  # bytes of the header block read by the fallback
MAX_RAW_BYTES = 262_144  # a message is read up to here and no further; the mailbox is asked for no more than this either
HEADER_VALUE_LIMIT = 2_000  # characters of one header value (folded lines included) handed to the standard library parser
HEADER_BLOCK_LIMIT = 65_536  # bytes of one block of header lines
HTML_LIMIT = 200_000  # characters of a web page body whose tags are stripped
TAG_LIMIT = 2_000  # a "<" with no ">" within this many characters is plain text
PARSE_SECONDS = 5.0  # a message that takes longer than this to read is kept as raw text
MESSAGE_ID = re.compile(r"<[^<>\s]+>")
HEADER_ID = re.compile(r"^message-id:\s*(<[^<>\s]+>)", re.I | re.M)
BLANK_LINE = re.compile(rb"\r?\n[ \t]*\r?\n")
BOUNDARY_LINE = re.compile(rb"--[\w'()+_,./:=?-]{1,70}[ \t]*\r?\n?")  # "--" and the boundary text, nothing else on the line ("-- " alone, a signature mark, is not one)
ASCII_LOWER = {c: c + 32 for c in range(65, 91)}  # upper to lower case without ever changing the length of the text
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


def strip_tags(markup: str) -> str:
    """The text of a web page body without its tags, scripts and styles, in one pass: a position is never looked at twice (the old pattern restarted a search at every
    "<script" and took minutes on a megabyte of them). A script or style block with no end, or a "<" with no ">" after it, ends the text there."""
    low = markup.translate(ASCII_LOWER)
    out: list[str] = []
    i, n, gt = 0, len(markup), -2
    while i < n:
        lt = markup.find("<", i)
        if lt == -1:
            out.append(markup[i:])
            break
        out.append(markup[i:lt])
        name = "script" if low.startswith("<script", lt) else "style" if low.startswith("<style", lt) else ""
        if name and not low[lt + 1 + len(name): lt + 2 + len(name)].isalnum():
            close = low.find("</" + name, lt)
            end = markup.find(">", close) if close != -1 else -1
            if end == -1:
                break  # no end to the block: the rest of it is not text
            out.append(" ")
            i = end + 1
            continue
        if gt != -1 and gt < lt:
            gt = markup.find(">", lt + 1)
        if gt == -1:
            out.append(markup[lt:])  # no tag can end after this point, so what is left is text
            break
        if gt - lt <= TAG_LIMIT:
            out.append(" ")
            i = gt + 1
        else:
            out.append("<")
            i = lt + 1
    return "".join(out)


def _body_text(msg) -> tuple[str, str]:
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return "", ""
    text, note = _part_text(part)
    if part.get_content_type() == "text/html":
        text = html.unescape(strip_tags(text[:HTML_LIMIT]))
    return text, note


class ParseTimeout(BaseException):
    """Raised inside a parse that ran out of time. A BaseException on purpose: the decoding code catches Exception and must not swallow it."""


@contextmanager
def time_limit(seconds: float) -> Iterator[None]:
    """Stop the block after `seconds`. Needs SIGALRM and the main thread (the worker has both); anywhere else it does nothing and the size limits are the protection."""
    if not hasattr(signal, "setitimer") or threading.current_thread() is not threading.main_thread():
        yield
        return

    def fire(signum, frame):
        raise ParseTimeout()

    previous = signal.signal(signal.SIGALRM, fire)
    started = time.monotonic()
    before = signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
        if before[0] > 0:  # somebody else's timer was running: give it back, minus the time used here
            signal.setitimer(signal.ITIMER_REAL, max(0.001, before[0] - (time.monotonic() - started)))


def limit_headers(raw: bytes) -> bytes:
    """The message with every header value cut to HEADER_VALUE_LIMIT characters and every block of header lines to HEADER_BLOCK_LIMIT bytes. Header lines are the lines
    before the first blank line and the lines after a boundary line ("--...") up to the next blank line; the text of the message is left as it is."""
    out: list[bytes] = []
    entry: list[bytes] = []
    in_headers, block_bytes = True, 0

    def flush() -> None:
        if sum(map(len, entry)) <= HEADER_VALUE_LIMIT:
            out.extend(entry)
        else:
            out.append(entry[0][:HEADER_VALUE_LIMIT].rstrip(b"\r\n") + b"\n")
        entry.clear()

    for line in raw.splitlines(keepends=True):
        if in_headers:
            if not line.strip():
                flush()
                in_headers, block_bytes = False, 0
                out.append(line)
                continue
            block_bytes += len(line)
            if block_bytes > HEADER_BLOCK_LIMIT:
                continue  # the rest of an enormous block of header lines is dropped
            if line[:1] in (b" ", b"\t") and entry:
                entry.append(line)
            else:
                flush()
                entry.append(line)
        else:
            if BOUNDARY_LINE.fullmatch(line):
                in_headers, block_bytes = True, 0
            out.append(line)
    flush()
    return b"".join(out)


def parse_inbound(uid: str, raw: bytes, total_size: int | None = None) -> InboundEmail:
    """One raw message to an InboundEmail. Never raises. `total_size` is how big the whole message is in the mailbox when only its first part was fetched."""
    large = len(raw) > MAX_RAW_BYTES or (total_size or 0) > len(raw) or (total_size is None and len(raw) == MAX_RAW_BYTES)
    raw = limit_headers(raw[:MAX_RAW_BYTES])
    try:
        with time_limit(PARSE_SECONDS):
            got = _parse(uid, raw)
    except ParseTimeout:
        return _salvage(uid, raw, "took too long")
    except Exception as exc:  # RecursionError on deeply nested parts, header errors, anything: the message is kept
        return _salvage(uid, raw, type(exc).__name__)
    if large:
        notes = [got.parse_problem[7:]] if got.parse_problem else []
        got = dataclasses.replace(got, parse_problem=("parse: " + "; ".join(["large message, only the first 256 KB were read", *notes]))[:120])
    return got


def _auto_reply(msg) -> bool:
    """The message says it was written by a machine: Auto-Submitted (anything but "no"), X-Autoreply, X-Autorespond, or a Precedence of auto_reply."""
    submitted = str(msg["Auto-Submitted"] or "").strip().lower()
    precedence = str(msg["Precedence"] or "").strip().lower()
    return bool((submitted and submitted != "no") or msg["X-Autoreply"] or msg["X-Autorespond"] or precedence in {"auto_reply", "auto-reply", "autoreply"})


def _parse(uid: str, raw: bytes) -> InboundEmail:
    msg = email.message_from_bytes(raw, policy=default_policy)
    text, note = _body_text(msg)
    is_dsn, refs = delivery_report_facts(msg)
    action, status = delivery_status_of(msg) if is_dsn else ("", "")
    return InboundEmail(
        external_id=str(msg["Message-ID"] or f"imap-{uid}"), from_addr=parseaddr(str(msg["From"] or ""))[1], to_addr=parseaddr(str(msg["To"] or ""))[1],
        subject=str(msg["Subject"] or ""), body=text[:TEXT_LIMIT], is_dsn=is_dsn, references=refs, auth_results=str(msg["Authentication-Results"] or "")[:300], uid=uid,
        dsn_action=action, dsn_status=status, parse_problem=f"parse: {note}"[:120] if note else "", auto_reply=_auto_reply(msg),
    )


def _header(block: str, name: str) -> str:
    m = re.search(rf"^{name}:[ \t]*(.*(?:\r?\n[ \t]+.*)*)", block, re.I | re.M)
    return re.sub(r"\s*\r?\n\s*", " ", m.group(1)).strip()[:HEADER_VALUE_LIMIT] if m else ""


def _decoded(value: str) -> str:
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _salvage(uid: str, raw: bytes, why: str) -> InboundEmail:
    """The whole message as text, flagged. Sender, subject and the ids it answers come from the header lines; the body is everything after them, decoded loosely."""
    cut = BLANK_LINE.search(raw[:MAX_RAW_BYTES])
    block = (raw[: cut.start()] if cut else raw[:HEADER_LIMIT])[:HEADER_LIMIT].decode("utf-8", "replace")
    body = (raw[cut.end():] if cut else b"")[: TEXT_LIMIT * 4].decode("utf-8", "replace").replace("\x00", "")
    refs = tuple(dict.fromkeys(MESSAGE_ID.findall(_header(block, "In-Reply-To")) + MESSAGE_ID.findall(_header(block, "References"))))[:20]
    mid = MESSAGE_ID.search(_header(block, "Message-ID"))
    return InboundEmail(
        external_id=mid.group(0) if mid else f"imap-{uid}", from_addr=parseaddr(_header(block, "From"))[1], to_addr=parseaddr(_header(block, "To"))[1],
        subject=_decoded(_header(block, "Subject"))[:300], body=body[:TEXT_LIMIT], references=refs, uid=uid, parse_problem=f"parse: unreadable ({why})"[:120], unreadable=True,
    )
