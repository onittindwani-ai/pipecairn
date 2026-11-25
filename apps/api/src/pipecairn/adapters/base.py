"""Adapter interfaces and shared helpers. Every category has an offline `seed` adapter."""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol
from urllib.parse import urlparse

from sendora_core.adapters import AdapterError


@dataclass
class InboundEmail:
    external_id: str
    from_addr: str
    to_addr: str
    subject: str
    body: str
    received_at: datetime | None = None
    # What the mail itself proves. A delivery failure notice is believed only when it is a real delivery status report (is_dsn) that
    # names the Message-ID of a message we sent (references). Anyone can type "mail delivery failed" into a From line.
    is_dsn: bool = False
    references: tuple[str, ...] = ()
    auth_results: str = ""  # the Authentication-Results header the receiving server added (SPF, DKIM, DMARC), kept for the audit note
    uid: str = ""  # the mailbox's own id for the message, so it can be marked as read AFTER it is safely stored (empty for the offline inbox and webhooks)
    # What the delivery status report says, read from its own Action and Status lines (never from the words around them). Empty when it has none.
    dsn_action: str = ""  # failed, delayed, delivered, relayed, expanded
    dsn_status: str = ""  # for example 5.1.1 (permanent) or 4.4.1 (temporary)
    # Mail that could not be read cleanly. parse_problem says what was wrong ("parse: unknown charset foo-bar"); unreadable means the whole message was kept as raw text.
    parse_problem: str = ""
    unreadable: bool = False
    skipped: bool = False  # set by the inbox when it deliberately left the message alone (not from a lead): the poller then does not mark it as read
    # True when the mail itself says a machine wrote it (Auto-Submitted other than "no", X-Autoreply, X-Autorespond, Precedence auto_reply). False when it has no such header,
    # which is also what a mail relay that does not pass headers on looks like. Only with this header does a date or a ticket number alone count as an automatic reply.
    auto_reply: bool = False


@dataclass
class InboundSms:
    external_id: str
    from_number: str
    to_number: str
    text: str


@dataclass
class Booking:
    external_id: str
    starts_at: datetime
    ends_at: datetime


@dataclass
class PersonRecord:
    email: str
    first_name: str = ""
    last_name: str = ""
    title: str = ""
    phone: str = ""
    company: str = ""
    extra: dict = field(default_factory=dict)


@dataclass
class HandoffResult:
    package_path: str
    instructions: str
    sent: bool = False


class RecipientRefused(AdapterError):
    """The mail server refused this recipient for good (a 5xx answer at RCPT TO): the address is not deliverable."""

    external_id = ""


class SendUnconfirmed(AdapterError):
    """The message was handed to the mail server but the answer never came, so it may or may not have been accepted. It must not be sent again."""

    external_id = ""  # the Message-ID the message went out with, so a delivery report that arrives later can still be matched to it


class EmailAdapter(Protocol):
    def send(self, *, from_addr: str, to: str, subject: str, body: str) -> str: ...
    def fetch_replies(self) -> list[InboundEmail]: ...
    def mark_seen(self, uids: list[str]) -> None: ...
    def healthcheck(self) -> tuple[bool, str]: ...


class SmsAdapter(Protocol):
    def send(self, *, to: str, text: str) -> str: ...
    def healthcheck(self) -> tuple[bool, str]: ...


class CalendarAdapter(Protocol):
    def slots(self, start: datetime, end: datetime) -> list[datetime]: ...
    def book(self, *, start: datetime, name: str, email: str, timezone: str) -> Booking: ...
    def healthcheck(self) -> tuple[bool, str]: ...


class CrmAdapter(Protocol):
    def upsert_person(self, person: PersonRecord) -> str: ...
    def healthcheck(self) -> tuple[bool, str]: ...


class EsignAdapter(Protocol):
    def prepare(self, *, contract_pdf: bytes, title: str, signers: list[dict], open_items: list[str] | None = None, folder_key: str = "") -> HandoffResult: ...
    def healthcheck(self) -> tuple[bool, str]: ...


def safe_base_url(url: str, *, allow_http_local: bool = False, allow_private: bool = False) -> str:
    """Refuse base URLs that point at the local network or non web schemes (SSRF guard for URLs a user can set).

    Only https is accepted. Hosts that resolve to private, loopback, link local or reserved addresses are refused,
    unless `allow_http_local` is set (tests and a self hosted CRM on the same machine, a deliberate choice).
    """
    u = urlparse(url)
    if u.scheme not in {"https", "http"} or not u.hostname:
        raise AdapterError("The URL must start with https:// and include a host name.")
    if u.username or u.password:
        raise AdapterError("Put credentials in the key field, not in the URL.")
    local_ok = allow_http_local or allow_private  # ALLOW_PRIVATE_BASE_URLS: the owner chose a self hosted tool on a private address
    if u.scheme == "http" and not local_ok:
        raise AdapterError("Use an https:// URL.")
    try:
        infos = socket.getaddrinfo(u.hostname, u.port or (443 if u.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise AdapterError(f"The host {u.hostname} could not be found.") from exc
    private = []
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        is_private = ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified
        private.append(is_private)
        if is_private and not local_ok:
            raise AdapterError("That URL points at a private or local address, which is refused.")
    if u.scheme == "http" and not allow_http_local and not all(private):
        raise AdapterError("Plain http is accepted only for an address on a private network. Use an https:// URL for anything on the internet.")
    return url.rstrip("/")
