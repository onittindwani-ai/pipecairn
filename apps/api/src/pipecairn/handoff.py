"""E-signature hand off. The Breezedoc adapter prepares a folder (contract PDF, signers file, steps) for a person to send.

It does not call any signing API: whether Breezedoc offers one we can use was not confirmed. Nothing is sent from here.
"""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path

from pipecairn.adapters.base import HandoffResult
from pipecairn.util import csv_safe
from sendora_core.settings import BaseAppSettings

STEPS = """Send this contract for signature (steps are UNVERIFIED against the live Breezedoc screens, check them once):
1. Sign in to your Breezedoc account and start a new document.
2. Upload contract.pdf from this folder.
3. Add each person listed in signers.csv as a signer, in that order.
4. Place a signature field and a date field for each signer.
5. Review the open items listed in OPEN-ITEMS.txt. Do not send while any are open.
6. Send it. When it is signed, mark the deal as won in Pipecairn.
"""


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60] or "contract"


class BreezedocHandoff:
    def __init__(self, settings: BaseAppSettings, base_dir: Path | None = None):
        self.settings = settings
        self.base_dir = (base_dir or Path("handoff")).resolve()

    def prepare(self, *, contract_pdf: bytes, title: str, signers: list[dict], open_items: list[str] | None = None, folder_key: str = "") -> HandoffResult:
        """folder_key (the contract id) goes in front of the name, so two contracts with the same company and title never share a folder."""
        key = re.sub(r"[^a-z0-9]+", "", folder_key.lower())[:20]
        folder = (self.base_dir / (f"{key}-{slug(title)}" if key else slug(title))).resolve()
        if self.base_dir not in folder.parents and folder != self.base_dir:
            raise ValueError("Refused: the folder would be outside the hand off directory.")
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "contract.pdf").write_bytes(contract_pdf)
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["order", "name", "email"])
        for i, s in enumerate(signers, 1):
            w.writerow([i, csv_safe(s.get("name", "")), csv_safe(s.get("email", ""))])  # a name typed on a web form must not run as a spreadsheet formula
        (folder / "signers.csv").write_text(buf.getvalue(), newline="")
        (folder / "OPEN-ITEMS.txt").write_text("\n".join(f"- {x}" for x in (open_items or [])) or "None.")
        (folder / "INSTRUCTIONS.txt").write_text(STEPS)
        return HandoffResult(package_path=str(folder), instructions=STEPS, sent=False)

    def healthcheck(self) -> tuple[bool, str]:
        return True, "Prepares a folder only. Nothing is sent to Breezedoc automatically."
