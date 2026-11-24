"""Score the reply reader on a labelled set. Prints accuracy, per class precision and recall, and the confusion pairs.

The default model is the offline stand in (rules). It is NOT a language model, so these numbers say nothing about a
live model. Two sets exist:
  --set testset   data/reply_testset.json  (70 cases, written by the same author as the rules, so optimistic)
  --set heldout   data/reply_heldout.json  (written separately in different wording, the honest number)

Run: python tools/eval_replies.py --set heldout
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "apps" / "api" / "src"))

from pipecairn.offline_llm import OfflineBackend  # noqa: E402
from pipecairn.replies import classify_reply  # noqa: E402
from sendora_core.llm import LLM  # noqa: E402
from sendora_core.settings import BaseAppSettings  # noqa: E402

SETS = {"testset": "reply_testset.json", "heldout": "reply_heldout.json", "heldout2": "reply_heldout2.json"}


def load_cases(name: str) -> list[dict]:
    data = json.loads((ROOT / "data" / SETS[name]).read_text(encoding="utf-8"))
    return data["cases"] if isinstance(data, dict) else data


def per_class(cases: list[dict], predicted: list[str]) -> dict[str, dict]:
    labels = sorted({c["intent"] for c in cases} | set(predicted))
    out: dict[str, dict] = {}
    for lab in labels:
        tp = sum(1 for c, p in zip(cases, predicted) if c["intent"] == lab and p == lab)
        fp = sum(1 for c, p in zip(cases, predicted) if c["intent"] != lab and p == lab)
        fn = sum(1 for c, p in zip(cases, predicted) if c["intent"] == lab and p != lab)
        out[lab] = {
            "support": tp + fn,
            "precision": round(tp / (tp + fp), 3) if tp + fp else None,
            "recall": round(tp / (tp + fn), 3) if tp + fn else None,
        }
    return out


def evaluate(name: str) -> dict:
    cases = load_cases(name)
    llm = LLM(BaseAppSettings(_env_file=None), OfflineBackend())
    predicted = [classify_reply(c["text"], llm).intent for c in cases]
    correct = sum(1 for c, p in zip(cases, predicted) if c["intent"] == p)
    confusion = Counter((c["intent"], p) for c, p in zip(cases, predicted) if c["intent"] != p)
    failures = [{"id": c["id"], "expected": c["intent"], "got": p, "text": c["text"][:90]} for c, p in zip(cases, predicted) if c["intent"] != p]
    # the safety slice: a stop request or an adversarial reply that was not read correctly
    stop_missed = sum(1 for c, p in zip(cases, predicted) if c["intent"] == "unsubscribe" and p != "unsubscribe")
    return {
        "set": name,
        "model": "offline stand in (rules), NOT a language model",
        "total": len(cases),
        "correct": correct,
        "accuracy": round(correct / len(cases), 4),
        "per_class": per_class(cases, predicted),
        "confusion_pairs": [{"expected": e, "got": g, "count": n} for (e, g), n in confusion.most_common()],
        "unsubscribe_missed": stop_missed,
        "failures": failures,
    }


def short(r: dict) -> dict:
    return {"total": r["total"], "correct": r["correct"], "accuracy": r["accuracy"], "unsubscribe_missed": r["unsubscribe_missed"]}


def summary() -> dict:
    """The numbers quoted in the README and docs. First runs are read from the files saved at the time, never recomputed."""
    ev = ROOT / "data" / "eval"
    first = lambda n: short(json.loads((ev / n).read_text(encoding="utf-8")))  # noqa: E731
    return {
        "model": "offline stand in (rules), NOT a language model",
        "testset_same_author_as_rules": short(evaluate("testset")),
        "heldout_first_run_reported": first("heldout_first_run.json"),
        "heldout2_first_run_after_tuning_partly_held_out": first("heldout2_first_run.json"),
        "heldout_after_tuning_no_longer_held_out": short(evaluate("heldout")),
    }


def main(argv: list[str] | None = None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--set", choices=sorted(SETS), default="testset")
    ap.add_argument("--write-summary", action="store_true", help="write data/eval/summary.json")
    args = ap.parse_args(argv)
    if args.write_summary:
        out = summary()
        (ROOT / "data" / "eval" / "summary.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
        print(json.dumps(out, indent=1))
        return out
    out = evaluate(args.set)
    print(json.dumps(out, indent=1, ensure_ascii=False))
    return out


if __name__ == "__main__":
    main()
