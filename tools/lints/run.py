#!/usr/bin/env python3
"""Run the custom GAIA Python AST lints and fail loud with teaching messages.

Usage:
    uv run --project apps/api python tools/lints/run.py apps/api/app [more/paths ...]

Each failure prints the rule, why it exists, the offending file:line, the exact
remediation, and a doc pointer — so the fix is obvious without leaving the error.
A rule that crashes (say ``ast.parse`` hitting syntax the running interpreter
cannot parse) is reported with the rule name and the file it died on, while
every other rule still runs — one broken rule must not hide the others'
findings. Exits non-zero if any rule reports violations OR crashes. Stdlib
only; wired into the ``static-python`` CI job and the api pre-commit config.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys
import traceback

# The rules parse app sources with the *running* interpreter's ``ast``, so an
# older python is not a degraded run — it crashes rules on syntax it cannot
# parse and stops matching CI. Fail loud here rather than diverge silently.
REQUIRED_PYTHON = (3, 12)
if sys.version_info < REQUIRED_PYTHON:
    _required = f"{REQUIRED_PYTHON[0]}.{REQUIRED_PYTHON[1]}"
    _running = f"{sys.version_info.major}.{sys.version_info.minor}"
    raise SystemExit(
        f"tools/lints/run.py needs Python {_required}+ (the version CI runs), got {_running} "
        f"at {sys.executable} — rerun with: uv run --project apps/api python tools/lints/run.py "
        f"{' '.join(sys.argv[1:]) or 'apps/api/app'}"
    )

from _common import display, iter_python_files, report_rule
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


def _crash_location(exc: Exception) -> str:
    """Best-effort ``file:line`` for a rule crash.

        ``ast.parse`` and the per-file reads both attach the offending path to the
    exception they raise (``SyntaxError.filename`` / ``OSError.filename``); for
    anything else the name is "unknown file" and the printed traceback says which
    file was being checked.
    """
    filename = getattr(exc, "filename", None)
    if not isinstance(filename, str):
        return "unknown file"
    shown = display(Path(filename))
    lineno = getattr(exc, "lineno", None)
    return f"{shown}:{lineno}" if isinstance(lineno, int) else shown


def main(argv: list[str]) -> int:
    paths = [Path(a) for a in argv] or [Path("apps/api/app")]
    files = iter_python_files(paths)

    total = 0
    crashed: list[str] = []
    for module in RULES:
        try:
            violations = module.check(files)
        except Exception as exc:
            # Containment, not swallowing: the crash is printed in full below
            # (rule name, file, traceback) and still fails the run — the goal
            # is only that one broken rule cannot hide the others' findings.
            location = _crash_location(exc)
            crashed.append(f"{module.RULE} ({location})")
            print(
                f"\n✗ {module.RULE} — crashed while checking {location}; remaining rules still ran",
                file=sys.stderr,
            )
            print(f"    {type(exc).__name__}: {exc}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            continue
        if violations:
            total += len(violations)
            report_rule(module.RULE, module.WHY, module.DOC, violations)

    if total or crashed:
        summary = f"{total} custom-lint violation(s) across {len(RULES)} rule(s)"
        if crashed:
            summary += f"; {len(crashed)} rule(s) crashed: {', '.join(crashed)}"
        print(
            f"\n{summary}. See tools/lints/README.md for each rule's rationale and remediation.",
            file=sys.stderr,
        )
        _write_summary(False, total, len(crashed), len(files))
        return 1

    print(f"custom python lints: {len(RULES)} rules passed on {len(files)} files")
    _write_summary(True, 0, 0, len(files))
    return 0


def _write_summary(ok: bool, total: int, crash_count: int, file_count: int) -> None:
    """Minimal human-facing lane summary for $GITHUB_STEP_SUMMARY."""

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary:
        return
    try:
        with open(summary, "a", encoding="utf-8") as f:
            if ok:
                f.write(
                    f"### Custom Python lints — ✅ passed ({len(RULES)} rules, {file_count} files)\n"
                )
            else:
                # A crashed rule checked nothing, so naming only the violation
                # count would render a crash-only run as "0 violation(s)" — the
                # lane summary would read like a pass.
                crashes = f", {crash_count} rule(s) crashed" if crash_count else ""
                f.write(
                    f"### Custom Python lints — ❌ {total} violation(s){crashes} "
                    f"({len(RULES)} rules)\n"
                )
                f.write("See `tools/lints/README.md` for rationale and remediation.\n")
    except OSError:
        pass


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
