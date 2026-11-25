import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_docs_pass_the_doc_checker():
    p = subprocess.run([sys.executable, str(ROOT / "tools" / "check_docs.py")], capture_output=True, text=True)
    assert p.returncode == 0, p.stdout


def test_measured_file_has_the_numbers_the_docs_quote():
    m = json.loads((ROOT / "data" / "measured.json").read_text())
    assert {"tests", "browser_tests", "screenshots", "adapters_registered", "contract_tests", "reader"} <= set(m)
    assert m["reader"]["set_b_first"]["total"] == 170


def test_a_reference_to_a_guide_that_does_not_exist_is_found(tmp_path):
    import importlib.util

    spec = importlib.util.spec_from_file_location("check_docs", ROOT / "tools" / "check_docs.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.DOC_NUMBER.findall("see `07` and `13` but not `40` or `99`") == ["07", "13"]
    assert not list((ROOT / "docs").glob("99-*.md"))
