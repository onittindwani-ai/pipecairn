import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import eval_replies  # noqa: E402

DATA = Path(__file__).resolve().parents[2] / "data"
INTENTS = {"interested", "question", "not_now", "wrong_person", "unsubscribe", "out_of_office", "bounce"}


def test_per_class_precision_and_recall_are_computed_from_counts():
    cases = [{"intent": "a"}, {"intent": "a"}, {"intent": "b"}, {"intent": "b"}]
    got = eval_replies.per_class(cases, ["a", "b", "b", "b"])
    assert got["a"] == {"support": 2, "precision": 1.0, "recall": 0.5}
    assert got["b"] == {"support": 2, "precision": round(2 / 3, 3), "recall": 1.0}


def test_heldout_file_is_labelled_fictional_and_big_enough():
    cases = eval_replies.load_cases("heldout")
    assert len(cases) >= 100
    assert {c["intent"] for c in cases} == INTENTS
    assert len({c["id"] for c in cases}) == len(cases)
    assert "fictional" in json.loads((DATA / "reply_heldout.json").read_text(encoding="utf-8"))["label"].lower()
    assert sum(1 for c in cases if c["adversarial"]) >= 5


def test_heldout_has_no_text_in_common_with_the_old_set():
    old = {c["text"].strip().lower() for c in eval_replies.load_cases("testset")}
    assert not [c for c in eval_replies.load_cases("heldout") if c["text"].strip().lower() in old]


def test_first_run_scores_are_kept_unchanged_for_the_record():
    first = json.loads((DATA / "eval" / "heldout_first_run.json").read_text(encoding="utf-8"))
    assert (first["total"], first["correct"]) == (134, 44)
    second = json.loads((DATA / "eval" / "heldout2_first_run.json").read_text(encoding="utf-8"))
    assert (second["total"], second["correct"]) == (42, 12)


def test_evaluate_reports_all_the_requested_numbers():
    out = eval_replies.evaluate("heldout")
    assert out["total"] == 134 and set(out["per_class"]) == INTENTS
    assert {"accuracy", "confusion_pairs", "failures", "unsubscribe_missed"} <= set(out)


def test_after_tuning_set_is_a_regression_check_only():
    # this set was used to fix the rules, so 100 percent here proves nothing about new wording
    assert eval_replies.evaluate("heldout")["unsubscribe_missed"] == 0


def test_summary_file_is_current():
    saved = json.loads((DATA / "eval" / "summary.json").read_text(encoding="utf-8"))
    assert saved == eval_replies.summary(), "run: python tools/eval_replies.py --write-summary"
