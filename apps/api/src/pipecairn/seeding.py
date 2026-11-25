"""Load the seed data into a database. Used by the demo, the tests and tools/score_seed.py."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from pipecairn import intake
from pipecairn.models import Company, Mailbox, Sequence, Step
from pipecairn.suppression import add_suppression

# Only a source checkout has the data folder next to the code. An installed copy (the Docker image) does not, so the folder named by
# SEED_DIR (settings.seed_dir) is always the first choice and this one is only the last resort.
REPO_DATA = Path(__file__).resolve().parents[4] / "data"
DEFAULT_DATA = REPO_DATA


def data_dir(seed_dir: str | Path | None = None) -> Path:
    """The folder that holds seed.json: SEED_DIR when it is set, otherwise the checkout's data folder when there is one. Says plainly when neither exists."""
    if seed_dir:
        found = Path(seed_dir)
    elif (REPO_DATA / "seed.json").is_file():
        found = REPO_DATA
    else:
        raise FileNotFoundError("The demo data folder was not found. Set SEED_DIR to the folder that holds seed.json.")
    if not (found / "seed.json").is_file():
        raise FileNotFoundError(f"There is no seed.json in the demo data folder {found}. Check SEED_DIR.")
    return found


def read_seed(folder: Path | str | None = None) -> dict:
    return json.loads((data_dir(folder) / "seed.json").read_text())


def load_seed(session: Session, seed: dict, now: datetime, with_leads: bool = True) -> dict:
    for c in seed["companies"]:
        session.add(Company(name=c["name"], domain=c["domain"], industry=c["industry"], size=c["size"], country=c["country"], is_customer=c["is_customer"]))
    session.flush()
    for s in seed["suppressions"]:
        add_suppression(session, s["kind"], s["value"], s["reason"], s["source"], actor="seed")
    for m in seed["mailboxes"]:
        session.add(Mailbox(address=m["address"], provider=m["provider"], daily_cap=m["daily_cap"], sent_today=m["sent_today"], sent_day=now.date().isoformat(),
                            sent_total=m["sent_total"], bounce_count=m["bounce_count"], warmup_days=m["warmup_days"], spf_ok=m["spf_ok"], dkim_ok=m["dkim_ok"], dmarc_ok=m["dmarc_ok"]))
    seq = Sequence(name=seed["sequence"]["name"], active=True)
    for i, st in enumerate(seed["sequence"]["steps"]):
        seq.steps.append(Step(position=i, channel=st["channel"], delay_hours=st["delay_hours"], subject=st["subject"], body=st["body"]))
    session.add(seq)
    session.flush()
    report = intake.import_leads(session, seed["leads"], now) if with_leads else None
    return {"sequence_id": seq.id, "import": report}
