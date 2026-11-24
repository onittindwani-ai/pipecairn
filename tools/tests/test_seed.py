import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
D = ROOT / "data"


def load(n):
    return json.loads((D / n).read_text())


def test_seed_is_deterministic(tmp_path):
    before = (D / "seed.json").read_bytes()
    subprocess.run([sys.executable, str(ROOT / "tools" / "make_seed.py")], check=True, capture_output=True)
    assert (D / "seed.json").read_bytes() == before


def test_answer_key_matches_seed():
    seed, key, counts = load("seed.json"), load("answer_key.json"), load("counts.json")
    emails = [l["email"].strip().lower() for l in seed["leads"]]
    assert counts["lead_rows"] == len(seed["leads"])
    assert counts["unique_leads_expected"] == len(set(emails))
    for e in key["role_based"] + key["invalid_email"] + key["suppressed_emails"] + key["perfect_fit"] + key["poor_fit"]:
        assert e.strip().lower() in emails
    assert key["duplicate_group_count"] == 10
    assert len(set(emails)) == len(emails) - 10
    assert set(key["suppressed_domains"]) <= {c["domain"] for c in seed["companies"]}
    assert all(e == e.strip().lower() for e in key["must_not_send"])


def test_reply_testset_labels():
    cases = load("reply_testset.json")
    intents = {"interested", "question", "not_now", "wrong_person", "unsubscribe", "out_of_office", "bounce"}
    assert {c["intent"] for c in cases} == intents
    assert len({c["id"] for c in cases}) == len(cases)
