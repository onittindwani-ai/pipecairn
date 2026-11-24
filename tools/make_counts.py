#!/usr/bin/env python3
"""Measure the numbers the docs quote and write them to data/measured.json.

Every count in README and docs/ comes from this file (the docs mark them as <!--n:path-->value<!--/n-->; tools/check_docs.py compares them).
  python3 tools/make_counts.py            measure and write (runs the Python tests once, with coverage)
  python3 tools/make_counts.py --fast     skip the test run and keep the last test and coverage numbers
The browser test count comes from `playwright test --list`; the number of browser runs and the screenshot check are not measured here.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "measured.json"
PY = str(ROOT / ".venv" / "bin" / "python") if (ROOT / ".venv" / "bin" / "python").exists() else sys.executable


def run_tests() -> dict:
    cov = ROOT / ".coverage-counts.json"
    p = subprocess.run([PY, "-m", "pytest", "-o", "addopts=", "-q", "-p", "no:warnings", "-p", "no:cacheprovider", "--cov=apps/api/src/pipecairn", f"--cov-report=json:{cov}"],
                       cwd=ROOT, capture_output=True, text=True)
    grab = lambda word: int(m.group(1)) if (m := re.search(rf"(\d+) {word}", p.stdout)) else 0  # noqa: E731
    pct = None
    if cov.exists():
        pct = round(json.loads(cov.read_text())["totals"]["percent_covered"])
        cov.unlink()
    return {"passed": grab("passed"), "skipped": grab("skipped"), "failed": grab("failed"), "coverage_percent": pct}


def adapters() -> int:
    sys.path.insert(0, str(ROOT / "apps" / "api" / "src"))
    from pipecairn.config import Settings
    from pipecairn.registry import build_registry

    reg = build_registry(Settings(_env_file=None))
    return len(reg.describe())


def reader() -> dict:
    ev = ROOT / "data" / "eval"
    ind = ev / "independent"
    load = lambda p: json.loads(p.read_text(encoding="utf-8"))  # noqa: E731
    a1, a2, b1 = load(ind / "set_a_first_run.json"), load(ind / "set_a_after_tuning.json"), load(ind / "set_b_first_run.json")
    pct = lambda r, k: round(100 * r[k] / r["total"], 1)  # noqa: E731
    return {
        "set_a_first": {"total": a1["total"], "strict": a1["strict_correct"], "strict_percent": pct(a1, "strict_correct"), "lenient": a1["lenient_correct"], "lenient_percent": pct(a1, "lenient_correct"), "stops_missed": a1["safety"]["clear_stop_requests_missed"]},
        "set_a_after": {"total": a2["total"], "strict": a2["strict_correct"], "strict_percent": pct(a2, "strict_correct"), "lenient": a2["lenient_correct"], "lenient_percent": pct(a2, "lenient_correct"), "stops_missed": a2["safety"]["clear_stop_requests_missed"]},
        "set_b_first": {"total": b1["total"], "strict": b1["strict_correct"], "strict_percent": pct(b1, "strict_correct"), "lenient": b1["lenient_correct"], "lenient_percent": pct(b1, "lenient_correct"), "stops_missed": b1["safety"]["clear_stop_requests_missed"], "clear_stops": b1["safety"]["clear_stop_requests"]},
        "old_heldout_first": {"total": load(ev / "heldout_first_run.json")["total"], "correct": load(ev / "heldout_first_run.json")["correct"]},
    }


def main(argv: list[str]) -> int:
    old = json.loads(OUT.read_text()) if OUT.exists() else {}
    scores = json.loads((ROOT / "data" / "tool_scores.json").read_text())
    lst = subprocess.run(["pnpm", "exec", "playwright", "test", "--list"], cwd=ROOT / "apps" / "web", capture_output=True, text=True).stdout
    mm = re.search(r"Total: (\d+) tests? in (\d+) files?", lst)
    contracts = len(re.findall(r"^def test_", (ROOT / "apps/api/tests/test_contracts.py").read_text(), re.M))
    data = {
        "measured_on": date.today().isoformat(),
        "tests": old.get("tests") if "--fast" in argv else run_tests(),
        "web_unit_tests": old.get("web_unit_tests", 5),
        "browser_tests": int(mm.group(1)) if mm else old.get("browser_tests"),
        "screenshots": len(list((ROOT / "docs" / "screenshots").glob("*.png"))),
        "adapters_registered": adapters(),
        "contract_tests": contracts,
        "tool_groups": len(scores["groups"]), "tools_scored": sum(len(g["tools"]) for g in scores["groups"]),
        "seed": json.loads((ROOT / "data" / "counts.json").read_text()),
        "reader": reader(),
    }
    OUT.write_text(json.dumps(data, indent=1) + "\n")
    print("OK wrote", OUT.relative_to(ROOT), json.dumps({k: data[k] for k in ("tests", "browser_tests", "screenshots", "adapters_registered", "contract_tests")}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
