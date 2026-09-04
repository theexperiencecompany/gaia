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

This script closes that gap: a violation is allowed only if it is (a) already
in the checked-in baseline, AND (b) its file is not touched by the current
PR. Touch a grandfathered file and its known violations stop being free --
fix them in the same PR, same as any other lint failure. A genuinely new
violation (new file, or a rule the file didn't already have) is never
grandfathered, touched or not.

Usage::

    python3 tools/lints/check_plr_complexity.py       # check (exits 1 on failure)
    python3 tools/lints/check_plr_complexity.py --update   # record the current baseline

Stdlib only, like the AST rules and the ignore-ratchet beside it.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from _common import Violation, report_rule

RULE = "plr-complexity-ratchet"
WHY = (
    "PLR0911/0912/0913/0915 complexity debt is grandfathered per file, but only "
    "until a PR touches that file -- then its known violations must be fixed, "
    "same as any new one"
)
DOC = "tools/lints/README.md#plr-complexity-ratchet"

_HERE = Path(__file__).resolve().parent
REPO_ROOT = _HERE.parents[1]
BASELINE = _HERE / "plr_complexity_baseline.txt"
CHANGES_SCRIPT = REPO_ROOT / "scripts" / "ci" / "changes.sh"
PLR_RULES = ("PLR0911", "PLR0912", "PLR0913", "PLR0915")
FULL_SENTINEL = "__FULL__"

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


def _touched_files() -> set[str] | None:
    """Files this PR changed, or ``None`` on a full/push scan (no diff to check)."""
    proc = subprocess.run(  # nosec B603 - fixed repo script argv, no shell
        [str(CHANGES_SCRIPT), "files", "py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    lines = [line for line in proc.stdout.splitlines() if line]
    if lines == [FULL_SENTINEL]:
        return None
    return set(lines)


def read_baseline() -> set[tuple[str, str]]:
    if not BASELINE.exists():
        return set()
    entries: set[tuple[str, str]] = set()
    for raw in BASELINE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        path, rule = line.split("\t")
        entries.add((path, rule))
    return entries


def write_baseline(entries: set[tuple[str, str]]) -> None:
    body = "\n".join(f"{path}\t{rule}" for path, rule in sorted(entries))
    BASELINE.write_text(f"{_BASELINE_HEADER}{body}\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    current = _current_violations()
    current_keys = set(current)

    if "--update" in argv:
        previous = read_baseline()
        write_baseline(current_keys)
        print(
            f"{RULE}: baseline updated -- {len(current_keys)} known violation(s) "
            f"(+{len(current_keys - previous)} / -{len(previous - current_keys)}). "
            "Commit the diff so the change is reviewable."
        )
        return 0

    baseline = read_baseline()
    touched = _touched_files()

    unexpected = current_keys - baseline
    must_fix_now: set[tuple[str, str]] = set()
    if touched is not None:
        must_fix_now = {(path, rule) for path, rule in baseline if path in touched}

    failures = unexpected | must_fix_now
    if failures:
        violations = []
        for path, rule in sorted(failures):
            is_new = (path, rule) in unexpected
            fix = (
                "new complexity violation -- simplify the function, or if it's "
                "a genuine one-off, justify it in review and add it to "
                "tools/lints/plr_complexity_baseline.txt with --update"
                if is_new
                else (
                    "this file is grandfathered for this rule, but this PR "
                    "touches it -- fix the violation now and delete its line "
                    "from tools/lints/plr_complexity_baseline.txt"
                )
            )
            label = "new" if is_new else "touched, grandfathered"
            violations.append(
                Violation(
                    path=Path(path),
                    line=current.get((path, rule), 0),
                    detail=f"{rule} ({label})",
                    fix=fix,
                )
            )
        report_rule(RULE, WHY, DOC, violations)
        return 1

    fixed = baseline - current_keys
    if fixed:
        print(f"{RULE}: {len(fixed)} grandfathered violation(s) no longer present -- nice.")
        for path, rule in sorted(fixed):
            print(f"  - {path} ({rule})")
        print("  Lock the win in with: python3 tools/lints/check_plr_complexity.py --update")

    print(f"{RULE}: {len(current_keys)} current violation(s), all grandfathered and untouched")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
