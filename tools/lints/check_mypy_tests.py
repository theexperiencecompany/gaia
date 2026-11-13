#!/usr/bin/env python3
"""Touch-to-fix ratchet for mypy errors in apps/api/tests.

The API tests were never type-checked, and the debt when they were switched on
is grandfathered per (file, error code) in tools/lints/mypy_tests_baseline.txt
until a PR touches that file. Mechanics live in _ratchet.py.

Usage::

    python3 tools/lints/check_mypy_tests.py           # check (exits 1 on failure)
    python3 tools/lints/check_mypy_tests.py --update  # record the current baseline
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

from _ratchet import REPO_ROOT, RatchetRule, run_ratchet

RULE = "mypy-tests-ratchet"
WHY = (
    "mypy debt in apps/api/tests is grandfathered per (file, error code), but only "
    "until a PR touches that file -- then its known errors must be fixed, same as "
    "any new one"
)
DOC = "tools/lints/README.md#mypy-tests-ratchet"

_HERE = Path(__file__).resolve().parent
BASELINE = _HERE / "mypy_tests_baseline.txt"
TESTS_ROOT = "apps/api/tests"

# Same environment and flags as api:type-check (apps/api/project.json); its own
# cache subdirectory, like the other mypy targets that share MYPY_CACHE_DIR.
_MYPY_CMD = [
    "uv",
    "run",
    "--project",
    "apps/api",
    "--frozen",
    "--group",
    "backend",
    "--group",
    "dev",
    "mypy",
    TESTS_ROOT,
    "--ignore-missing-imports",
    "--output",
    "json",
    "--cache-dir",
    f"{os.environ.get('MYPY_CACHE_DIR', '.mypy_cache')}/api-tests",
]

_BASELINE_HEADER = """\
# mypy apps/api/tests grandfather baseline.
# See tools/lints/check_mypy_tests.py -- this is a TOUCH-TO-FIX ratchet, not a
# static exemption: a file listed here only stays quiet while untouched. The
# moment a PR modifies a listed file, its errors here must be fixed in that same
# PR, and this line deleted. New errors (new file, or an error code a file
# didn't already have) are never grandfathered by this list.
#
# One line per (file, mypy error code), tab-separated, sorted. Regenerate with:
#   python3 tools/lints/check_mypy_tests.py --update
#
# A line may carry a third field, "deferred-until=YYYY-MM-DD; <reason>", to
# keep a touched file's known error from failing until that date (CI warns
# instead). Past the date it fails again: fix it, or renew the deferral with a
# fresh reason. --update keeps the field.
"""


def _current_errors() -> dict[tuple[str, str], int]:
    """Every (file, error code) mypy reports under apps/api/tests, mapped to its first line."""
    proc = subprocess.run(  # nosec B603 - fixed uv/mypy argv, no shell
        _MYPY_CMD,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode not in (0, 1):
        print(proc.stdout, proc.stderr, sep="\n", file=sys.stderr)
        raise SystemExit(f"{RULE}: mypy failed unexpectedly (exit {proc.returncode})")
    out: dict[tuple[str, str], int] = {}
    for line in proc.stdout.splitlines():
        error = json.loads(line)
        if error["severity"] != "error":
            continue
        path = Path(error["file"]).resolve().relative_to(REPO_ROOT).as_posix()
        out.setdefault((path, error["code"]), error["line"])
    if proc.returncode == 1 and not out:
        print(proc.stdout, proc.stderr, sep="\n", file=sys.stderr)
        raise SystemExit(f"{RULE}: mypy exited 1 but reported no parseable error")
    return out


_RATCHET = RatchetRule(
    name=RULE,
    why=WHY,
    doc=DOC,
    baseline=BASELINE,
    header=_BASELINE_HEADER,
    script="tools/lints/check_mypy_tests.py",
    fix_new="new mypy error in a test -- type the fixture, mock or call properly",
)


def main(argv: list[str]) -> int:
    return run_ratchet(_RATCHET, _current_errors(), argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
