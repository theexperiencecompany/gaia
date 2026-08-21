#!/usr/bin/env python3
"""Run the custom GAIA Python AST lints and fail loud with teaching messages.

Usage:
    python3 tools/lints/run.py apps/api/app [more/paths ...]

Each failure prints the rule, why it exists, the offending file:line, the exact
remediation, and a doc pointer — so the fix is obvious without leaving the error.
Exits non-zero if any rule reports a violation. Stdlib only; wired into the
``static-python`` CI job and the api pre-commit config.
"""

from __future__ import annotations

from pathlib import Path
import sys

from _common import iter_python_files, report_rule
import no_service_classes
import no_silent_fallback
import repository_boundaries
import route_contract
import tool_dump_boundary
import wide_events_logging

RULES = (
    route_contract,
    no_service_classes,
    wide_events_logging,
    repository_boundaries,
    no_silent_fallback,
    tool_dump_boundary,
)


def main(argv: list[str]) -> int:
    paths = [Path(a) for a in argv] or [Path("apps/api/app")]
    files = iter_python_files(paths)

    total = 0
    for module in RULES:
        violations = module.check(files)
        if violations:
            total += len(violations)
            report_rule(module.RULE, module.WHY, module.DOC, violations)

    if total:
        print(
            f"\n{total} custom-lint violation(s) across {len(RULES)} rule(s). "
            "See tools/lints/README.md for each rule's rationale and remediation.",
            file=sys.stderr,
        )
        return 1

    print(f"custom python lints: {len(RULES)} rules passed on {len(files)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
