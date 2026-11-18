"""The truth oracle: rebuild the world, check every stored brief against it, write findings.json."""

import json
from pathlib import Path

from briefsim.oracle.checks import missing_briefs, run_checks
from briefsim.oracle.logs import logged_errors
from briefsim.oracle.truth import load, parse_instant


def write_findings(out: Path) -> None:
    truth = load(out)
    run = json.loads((out / "run.json").read_text())
    errors = logged_errors(out, truth.connected_at)
    findings = run_checks(truth) + missing_briefs(
        truth, int(run["days"]), parse_instant(run["origin"]), errors
    )
    findings.sort(key=lambda f: (f["day"], f["check"]))
    (out / "findings.json").write_text(json.dumps(findings, indent=1, ensure_ascii=False) + "\n")
