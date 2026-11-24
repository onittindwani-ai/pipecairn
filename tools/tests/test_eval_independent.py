import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import eval_independent  # noqa: E402


def _set(tmp_path, rows):
    inputs = [{"id": r[0], "from_name": "N", "from_address": "a@x.example.test", "subject": "s", "body": r[1]} for r in rows]
    key = [{"id": r[0], "label": r[2], "acceptable": r[3], "ambiguous": r[4], "tags": r[5]} for r in rows]
    (tmp_path / "input.json").write_text(json.dumps(inputs))
    (tmp_path / "key.json").write_text(json.dumps(key))
    return tmp_path


def test_load_joins_key_by_id_and_accepts_a_keyed_object(tmp_path):
    folder = _set(tmp_path, [("1", "hi", "question", ["question"], False, ["t"])])
    items = eval_independent.load_set(folder)
    assert items[0]["label"] == "question" and items[0]["tags"] == ["t"]
    key = {"1": {"label": "question", "acceptable": ["question", "not_now"], "ambiguous": True, "tags": []}}
    (folder / "key.json").write_text(json.dumps(key))
    assert eval_independent.load_set(folder)[0]["acceptable"] == ["not_now", "question"]


def test_strict_and_lenient_scores_and_safety_counts(tmp_path):
    rows = [("1", "x", "unsubscribe", ["unsubscribe"], False, []), ("2", "x", "unsubscribe", ["unsubscribe", "not_now"], True, ["trap"]),
            ("3", "x", "question", ["question"], False, []), ("4", "x", "interested", ["interested"], False, ["injection"])]
    items = eval_independent.load_set(_set(tmp_path, rows))
    got = eval_independent.score(items, ["question", "not_now", "question", "interested"])
    assert got["strict_correct"] == 2 and got["lenient_correct"] == 3
    assert got["ambiguous"] == {"count": 1, "strict_accuracy": 0.0, "lenient_accuracy": 1.0}
    assert got["safety"]["clear_stop_requests"] == 1 and got["safety"]["clear_stop_requests_missed"] == 1
    assert got["by_tag"]["trap"]["lenient"] == 1.0
    assert got["confusion_matrix_rows_expected_cols_got"]["unsubscribe"]["question"] == 1
    assert got["per_class_strict"]["question"] == {"support": 1, "precision": 0.5, "recall": 1.0}
    assert [f["id"] for f in got["failures_outside_acceptable"]] == ["1"]
    # a reply read as interested when only a refusal is acceptable is reported as a safety miss
    assert got["safety"]["injections_read_as_interested"] == 0


def test_evaluate_runs_the_real_reader_on_a_tiny_set(tmp_path):
    folder = _set(tmp_path, [("1", "Please unsubscribe me", "unsubscribe", ["unsubscribe"], False, [])])
    out = eval_independent.evaluate(folder, "tiny")
    assert out["strict_correct"] == 1 and "NOT a language model" in out["model"]
