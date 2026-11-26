"""Telnyx texting. Written from the public docs: POST /v2/messages with a Bearer key, Ed25519 signed webhooks (UNVERIFIED live).

US texting needs the client's own carrier registration first (10DLC brand and campaign). This adapter cannot do that for you.
"""

from __future__ import annotations

import base64
import time

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from pipecairn.adapters.base import InboundSms, safe_base_url
from sendora_core.adapters import AdapterError
from sendora_core.safety import write_action

TOLERANCE_S = 300


def verify_telnyx_webhook(public_key_b64: str, body: bytes, signature_b64: str, timestamp: str, now: float | None = None) -> bool:
    """Signature is Ed25519 over `timestamp|body`. Requests older than five minutes are refused."""
    try:
        if abs((now or time.time()) - int(timestamp)) > TOLERANCE_S:
            return False
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64))
        key.verify(base64.b64decode(signature_b64), timestamp.encode() + b"|" + body)
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


def parse_inbound(body: dict) -> InboundSms:
    d = body["data"]
    if d.get("event_type") != "message.received":
        raise AdapterError("Not an inbound message event.")
    p = d["payload"]
    return InboundSms(external_id=str(p.get("id") or d.get("id")), from_number=p["from"]["phone_number"], to_number=(p.get("to") or [{}])[0].get("phone_number", ""), text=p.get("text", ""))


class TelnyxSms:
    def __init__(self, settings, client: httpx.Client | None = None):
        self.settings = settings
        if client is not None:
            self.client = client
        else:
            if not settings.telnyx_api_key:
                raise AdapterError("TELNYX_API_KEY is empty.")
            self.client = httpx.Client(base_url=safe_base_url(settings.telnyx_base_url, allow_private=getattr(settings, "allow_private_base_urls", False)), timeout=15, headers={"Authorization": f"Bearer {settings.telnyx_api_key}"})

    @write_action("sms.send")
    def send(self, *, to: str, text: str) -> str:
        r = self.client.post("/v2/messages", json={"from": self.settings.telnyx_from_number, "to": to, "text": text})
        if r.status_code == 401:
            raise AdapterError("Telnyx rejected the API key.")
        if r.status_code >= 400:
            err = (r.json().get("errors") or [{}])[0]
            raise AdapterError(f"Telnyx refused the text: {err.get('detail') or err.get('title') or r.status_code}")
        return str(r.json()["data"]["id"])

    def healthcheck(self) -> tuple[bool, str]:
        if not self.settings.telnyx_from_number:
            return False, "TELNYX_FROM_NUMBER is empty."
        try:
            r = self.client.get("/v2/messages/healthcheck-probe")
        except httpx.HTTPError as exc:
            return False, f"Could not reach Telnyx: {type(exc).__name__}."
        if r.status_code == 401:
            return False, "Telnyx rejected the API key."
        return True, "Telnyx answered and accepted the key (a 404 for the probe id is expected)."
