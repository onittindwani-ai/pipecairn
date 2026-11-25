"""The opt out lines every message carries: a footer in the text and the List-Unsubscribe headers, plus the signed one click link.

A link made here proves one thing: the address in it was written into a message this system sent (the signature uses the session
secret). It never expires, because a person may click an old email.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from typing import Any

OPT_OUT_WORDS = ("reply stop", "unsubscribe", "reply \"stop\"", "text stop")


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _sig(secret: str, email: str) -> str:
    return _b64(hmac.new(secret.encode(), b"unsubscribe:" + email.encode(), hashlib.sha256).digest())


def make_token(secret: str, email: str) -> str:
    email = email.strip().lower()
    return f"{_b64(email.encode())}.{_sig(secret, email)}"


def read_token(secret: str, token: str) -> str | None:
    """The address in a valid token, otherwise None."""
    try:
        body, sig = token.split(".", 1)
        email = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)).decode()
    except (ValueError, UnicodeDecodeError):
        return None
    return email if hmac.compare_digest(sig.encode(), _sig(secret, email).encode()) else None


def unsubscribe_url(settings: Any, email: str) -> str:
    base = (getattr(settings, "public_base_url", "") or "").rstrip("/")
    return f"{base}/api/webhooks/unsubscribe/{make_token(settings.session_secret, email)}" if base.startswith("https://") else ""


def has_opt_out(text: str) -> bool:
    low = text.lower()
    return any(w in low for w in OPT_OUT_WORDS)


def with_footer(settings: Any, channel: str, body: str) -> str:
    """The body plus what the law and the mail providers expect: who is writing, where they are, and how to say stop.
    A line the template already has is not repeated. A text message only gets the stop line."""
    text = body.rstrip()
    if channel == "sms":
        return text if "stop" in text.lower() else f"{text} Reply STOP to opt out."
    name = (getattr(settings, "company_name", "") or "").strip()
    address = (getattr(settings, "company_address", "") or "").strip()
    low = text.lower()
    lines: list[str] = []
    if name and name.lower() not in low:
        lines.append(name)
    if address and address.lower() not in low:
        lines.append(address)
    if not has_opt_out(text):
        lines.append("Reply STOP to opt out of these emails.")
    return text + ("\n\n--\n" + "\n".join(lines) if lines else "")


def list_unsubscribe_headers(settings: Any, from_addr: str, to: str) -> dict[str, str]:
    """List-Unsubscribe always has a mailto (a reply with the word unsubscribe is read by the inbox job). With PUBLIC_BASE_URL set it also
    has the https link and the one click header that Gmail and Yahoo ask for."""
    parts = [f"<mailto:{from_addr}?subject=unsubscribe>"]
    out: dict[str, str] = {}
    url = unsubscribe_url(settings, to)
    if url:
        parts.append(f"<{url}>")
        out["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    out["List-Unsubscribe"] = ", ".join(parts)
    return out
