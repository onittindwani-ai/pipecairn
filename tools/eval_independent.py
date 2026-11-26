"""Score the reply reader on an independent held out set (written by a separate AI test author who never saw the code).

Each set folder holds `input.json` (a list of messages: id, from_name, from_address, subject, body) and `key.json` (one entry per id:
label, acceptable, ambiguous, tags). The tool reads the reply the way the product does (the message body, and the subject for delivery notices) and reports:

- strict accuracy: the reader's answer equals the primary label
- lenient accuracy: the reader's answer is any label the key calls acceptable
- both again on the non ambiguous items only, and the lenient score on the ambiguous items
- per class precision and recall (strict), and a confusion matrix
- accuracy per tag (quoted tails, footers, injections, other languages and so on)
- the safety slice: stop requests missed, and replies wrongly read as a stop request

The default reader is the offline stand in (rules). It is NOT a language model. Numbers say nothing about a live model.

Run: python tools/eval_independent.py --set a --out data/eval/independent/set_a_first_run.json
The first run of a set is saved untouched and is the reported number. Never tune on a set and call it held out.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "apps" / "api" / "src"))

LABELS = ["interested", "question", "not_now", "wrong_person", "unsubscribe", "out_of_office", "bounce"]
BASE = ROOT / "data" / "eval" / "independent"


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_set(folder: Path) -> list[dict]:
    """Join input.json and key.json on id. The key may be a list of entries with an id or an object keyed by id."""
    inputs = _read(folder / "input.json")
    inputs = inputs["items"] if isinstance(inputs, dict) and "items" in inputs else inputs
    raw_key = _read(folder / "key.json")
    if isinstance(raw_key, dict) and "items" in raw_key:
        raw_key = raw_key["items"]
    key = {str(k["id"]): k for k in raw_key} if isinstance(raw_key, list) else {str(k): v for k, v in raw_key.items()}
    out = []
    for m in inputs:
        k = key[str(m["id"])]
        label = k["label"]
        out.append({
            "id": str(m["id"]), "subject": m.get("subject", ""), "body": m.get("body", ""),
            "label": label, "acceptable": sorted(set(k.get("acceptable") or [label]) | {label}),
            "ambiguous": bool(k.get("ambiguous", False)), "tags": list(k.get("tags", [])),
        })
    if len(out) != len(key):
        raise ValueError(f"input has {len(out)} messages but the key has {len(key)} entries")
    return out


def read_all(items: list[dict], llm) -> list[str]:
    from pipecairn.replies import classify_reply

    return [classify_reply(it["body"], llm, it["subject"]).intent for it in items]


def _ratio(n: int, d: int) -> float | None:
    return round(n / d, 4) if d else None


def per_class(items: list[dict], predicted: list[str], lenient: bool) -> dict[str, dict]:
    """Strict: the primary label is the truth. Lenient: an acceptable answer counts as the truth (the reader's own label)."""
    truth = [p if lenient and p in it["acceptable"] else it["label"] for it, p in zip(items, predicted)]
    out: dict[str, dict] = {}
    for lab in LABELS:
        tp = sum(1 for t, p in zip(truth, predicted) if t == lab and p == lab)
        fp = sum(1 for t, p in zip(truth, predicted) if t != lab and p == lab)
        fn = sum(1 for t, p in zip(truth, predicted) if t == lab and p != lab)
        out[lab] = {"support": tp + fn, "precision": _ratio(tp, tp + fp), "recall": _ratio(tp, tp + fn)}
    return out


def score(items: list[dict], predicted: list[str]) -> dict:
    n = len(items)
    strict = [p == it["label"] for it, p in zip(items, predicted)]
    lenient = [p in it["acceptable"] for it, p in zip(items, predicted)]
    firm = [i for i, it in enumerate(items) if not it["ambiguous"]]
    soft = [i for i, it in enumerate(items) if it["ambiguous"]]
    confusion = {a: {b: 0 for b in LABELS} for a in LABELS}
    for it, p in zip(items, predicted):
        confusion[it["label"]][p if p in LABELS else "question"] += 1
    by_tag: dict[str, list[int]] = defaultdict(list)
    for i, it in enumerate(items):
        for t in it["tags"]:
            by_tag[t].append(i)
    tag_rows = {t: {"count": len(ix), "strict": _ratio(sum(strict[i] for i in ix), len(ix)), "lenient": _ratio(sum(lenient[i] for i in ix), len(ix))}
                for t, ix in sorted(by_tag.items())}
    stop_items = [i for i, it in enumerate(items) if it["label"] == "unsubscribe" and not it["ambiguous"]]
    pairs = Counter((it["label"], p) for it, p in zip(items, predicted) if p != it["label"])
    failures = [{"id": it["id"], "label": it["label"], "acceptable": it["acceptable"], "ambiguous": it["ambiguous"], "got": p, "tags": it["tags"],
                 "text": it["body"][:120].replace("\n", " ")} for it, p in zip(items, predicted) if p not in it["acceptable"]]
    return {
        "total": n,
        "strict_correct": sum(strict), "strict_accuracy": _ratio(sum(strict), n),
        "lenient_correct": sum(lenient), "lenient_accuracy": _ratio(sum(lenient), n),
        "non_ambiguous": {"count": len(firm), "strict_accuracy": _ratio(sum(strict[i] for i in firm), len(firm)),
                          "lenient_accuracy": _ratio(sum(lenient[i] for i in firm), len(firm))},
        "ambiguous": {"count": len(soft), "strict_accuracy": _ratio(sum(strict[i] for i in soft), len(soft)),
                      "lenient_accuracy": _ratio(sum(lenient[i] for i in soft), len(soft))},
        "per_class_strict": per_class(items, predicted, lenient=False),
        "per_class_lenient": per_class(items, predicted, lenient=True),
        "confusion_matrix_rows_expected_cols_got": confusion,
        "confusion_pairs": [{"expected": e, "got": g, "count": c} for (e, g), c in pairs.most_common()],
        "by_tag": tag_rows,
        "safety": {
            "clear_stop_requests": len(stop_items),
            "clear_stop_requests_missed": sum(1 for i in stop_items if predicted[i] != "unsubscribe"),
            "read_as_stop_when_stop_not_acceptable": sum(1 for it, p in zip(items, predicted) if p == "unsubscribe" and "unsubscribe" not in it["acceptable"]),
            "injections_read_as_interested": sum(1 for it, p in zip(items, predicted) if "injection" in it["tags"] and p == "interested" and "interested" not in it["acceptable"]),
        },
        "failures_outside_acceptable": failures,
    }


def evaluate(folder: Path, name: str, llm=None) -> dict:
    from pipecairn.offline_llm import OfflineBackend
    from sendora_core.llm import LLM
    from sendora_core.settings import BaseAppSettings

    items = load_set(folder)
    llm = llm or LLM(BaseAppSettings(_env_file=None), OfflineBackend())
    predicted = read_all(items, llm)
    return {"set": name, "model": "offline stand in (rules), NOT a language model", "input_read": "message body and subject (the body alone in the first run of set A)", **score(items, predicted)}


def main(argv: list[str] | None = None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--set", required=True, help="a, b, or a folder with input.json and key.json")
    ap.add_argument("--out", help="write the full result to this file")
    args = ap.parse_args(argv)
    folder = BASE / f"set_{args.set}" if args.set in {"a", "b"} else Path(args.set)
    result = evaluate(folder, args.set)
    text = json.dumps(result, indent=1, ensure_ascii=False) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    brief = {k: result[k] for k in ("set", "total", "strict_correct", "strict_accuracy", "lenient_correct", "lenient_accuracy", "non_ambiguous", "ambiguous", "safety")}
    print(json.dumps(brief, indent=1))
    return result


if __name__ == "__main__":
    main()
