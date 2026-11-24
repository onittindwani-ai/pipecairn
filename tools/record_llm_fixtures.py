"""Record the model answers for the seed replies into data/llm_fixtures/, so the demo can replay them with LLM_BACKEND=fixture.

IMPORTANT: these are NOT answers of a real model. The recording goes through the real anthropic code path (request building,
schema, response parsing) against a local fake server that answers with the offline stand in. So the fixtures prove the replay
path and the request shape, not model quality. Replace them with a recording from a real key (LLM_RECORD=true) when you have one.

Run: python tools/record_llm_fixtures.py
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "apps" / "api" / "src"))
sys.path.insert(0, str(ROOT))

from mock.anthropic_mock import FakeAnthropic  # noqa: E402
from pipecairn import model_tasks  # noqa: E402
from pipecairn.config import Settings  # noqa: E402
from pipecairn.offline_llm import OfflineBackend, draft_text  # noqa: E402
from pipecairn.replies import classify_reply  # noqa: E402
from sendora_core.llm import build_llm, reset_budgets  # noqa: E402

OUT = ROOT / "data" / "llm_fixtures"
NEEDS_A_DRAFT = {"interested", "question", "wrong_person"}


def answer_like_the_offline_reader(body: dict) -> str:
    content = body["messages"][0]["content"]
    return OfflineBackend().complete(model=body["model"], system=body.get("system", ""), prompt=content, max_tokens=body["max_tokens"]).text


def record() -> dict:
    seed = json.loads((ROOT / "data" / "seed.json").read_text(encoding="utf-8"))
    if OUT.exists():
        shutil.rmtree(OUT)
    counts = {"classify": 0, "draft": 0}
    with FakeAnthropic(answer_like_the_offline_reader) as fake:
        settings = Settings(_env_file=None, llm_backend="anthropic", anthropic_api_key="sk-ant-recording-key", anthropic_base_url=fake.url,
                            llm_record=True, llm_fixtures_dir=str(OUT), database_url="sqlite://")
        reset_budgets()
        llm = build_llm(settings, None)
        for item in seed["inbound_script"]:
            cls = classify_reply(item["text"], llm)
            if cls.source == "model":
                counts["classify"] += 1
            if cls.intent in NEEDS_A_DRAFT:
                model_tasks.write_draft(llm, cls.intent, "there", [], item["text"], draft_text(cls.intent, "there", []))
                counts["draft"] += 1
    counts["files"] = len(list(OUT.glob("*.json")))
    (OUT / "README.txt").write_text(
        "Recorded from a LOCAL FAKE server that answers with the offline stand in. Not answers of a real model.\n"
        "They prove the replay path and the request shape only. Regenerate: python tools/record_llm_fixtures.py\n", encoding="utf-8")
    return counts


if __name__ == "__main__":
    print(json.dumps(record()))
