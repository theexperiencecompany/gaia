#!/usr/bin/env python3
"""Touch-to-fix ratchet for ruff's PLR0911/0912/0913/0915 complexity rules.

``PLR0911``/``PLR0912``/``PLR0913``/``PLR0915`` (too many returns / branches /
arguments / statements) are re-enabled repo-wide, but the pre-existing debt at
the time they were switched on (``tools/lints/plr_complexity_baseline.txt``)
was too large to fix in one pass. A plain ``[tool.ruff.lint.per-file-ignores]``
entry would grandfather each listed file forever, silently, with no way to
notice a PR making an already-flagged function *worse* -- ruff's per-file
ignore silences a rule for the whole file, not just the violations recorded
at the time.

The ratchet mechanics (grandfathered only while untouched, expiring
deferrals, ``--update``) live in ``_ratchet.py`` and are shared with the other
baseline-carrying lints; this script only knows how to ask ruff for the
current violations.

Usage::

    python3 tools/lints/check_plr_complexity.py       # check (exits 1 on failure)
    python3 tools/lints/check_plr_complexity.py --update   # record the current baseline
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from _ratchet import REPO_ROOT, RatchetRule, run_ratchet

RULE = "plr-complexity-ratchet"
WHY = (
    "PLR0911/0912/0913/0915 complexity debt is grandfathered per file, but only "
    "until a PR touches that file -- then its known violations must be fixed, "
    "same as any new one"
)
DOC = "tools/lints/README.md#plr-complexity-ratchet"

_HERE = Path(__file__).resolve().parent
BASELINE = _HERE / "plr_complexity_baseline.txt"
PLR_RULES = ("PLR0911", "PLR0912", "PLR0913", "PLR0915")

# Pinned to the same ruff version as the "Python ruff" CI lane
# (.github/workflows/code-quality.yml) -- bump both together. `uvx` resolves
# it without requiring a separate "install ruff onto PATH" CI step.
_RUFF_CMD = ["uvx", "--no-build", "ruff@0.14.13"]

_BASELINE_HEADER = """\
# PLR0911/0912/0913/0915 complexity grandfather baseline.
# See tools/lints/check_plr_complexity.py -- this is a TOUCH-TO-FIX ratchet,
# not a static exemption: a file listed here only stays quiet while untouched.
# The moment a PR modifies a listed file, its violations here must be fixed in
# that same PR, and this line deleted. New violations (new file, or a rule a
# file didn't already have) are never grandfathered by this list.
#
# One line per (file, rule), tab-separated, sorted. Regenerate with:
#   python3 tools/lints/check_plr_complexity.py --update
#
# A line may carry a third field, "deferred-until=YYYY-MM-DD; <reason>", to
# keep a touched file's known violation from failing until that date (CI
# warns instead). Past the date it fails again: fix it, or renew the deferral
# with a fresh reason. --update keeps the field.
"""


def _current_violations() -> dict[tuple[str, str], int]:
    """Every (file, rule) violation in the repo right now, mapped to its line.

    Full-repo scan, keyed by (file, rule) to match the baseline's granularity
    -- if a file has several violations of the same rule, this keeps the
    first line encountered, which is enough to make a failure clickable.
    """
    proc = subprocess.run(  # nosec B603 - pinned ruff argv, no shell
        [
            *_RUFF_CMD,
            "check",
            "--select",
            ",".join(PLR_RULES),
            "--output-format",
            "json",
            ".",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode not in (0, 1):
        print(proc.stderr, file=sys.stderr)
        raise SystemExit(f"{RULE}: ruff failed unexpectedly (exit {proc.returncode})")
    violations = json.loads(proc.stdout)
    out: dict[tuple[str, str], int] = {}
    for v in violations:
        path = Path(v["filename"]).resolve().relative_to(REPO_ROOT).as_posix()
        key = (path, v["code"])
        out.setdefault(key, v["location"]["row"])
    return out


_RATCHET = RatchetRule(
    name=RULE,
    why=WHY,
    doc=DOC,
    baseline=BASELINE,
    header=_BASELINE_HEADER,
    script="tools/lints/check_plr_complexity.py",
    fix_new="new complexity violation -- simplify the function",
)


def main(argv: list[str]) -> int:
    return run_ratchet(_RATCHET, _current_violations(), argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
