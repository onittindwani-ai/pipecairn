import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import score_seed  # noqa: E402


def test_every_planted_trap_is_handled():
    r = score_seed.run()
    wrong = {k: v for k, v in r["checks"].items() if v[0] != v[1]}
    assert not wrong
