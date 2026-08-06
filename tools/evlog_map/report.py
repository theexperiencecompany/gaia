"""Render the map — terminal report, JSON contract, and GitHub step summary."""

from __future__ import annotations

import json
import os
from pathlib import Path

from rules import REQUIREMENTS
from scan import (
    MapResult,
    RouteEntry,
    classify_observability,
    scored_entries,
    waived_checks,
)

_BADGES = {"money": "$", "auth": "A", "pii": "@"}
_FIX_FIRST_COUNT = 3


def _display(path: Path) -> str:
    try:
        return os.path.relpath(path, Path.cwd())
    except ValueError:
        return str(path)


def _route_label(entry: RouteEntry) -> str:
    handler = entry.handler
    badge = _BADGES.get(entry.sensitivity.label, " ")
    if handler.kind in ("worker", "voice"):
        return f"{badge} {handler.kind} {handler.route_path}"
    verb = "/".join(m.upper() for m in handler.methods) or "WS"
    return f"{badge} {verb} {handler.route_path or handler.name}"


def _check_chips(entry: RouteEntry) -> str:
    parts = []
    titles = {rule.id: rule.title for rule in REQUIREMENTS}
    for check_id, result in entry.checks.items():
        if result.status == "n/a":
            continue
        mark = "ok" if result.status == "pass" else "x"
        parts.append(f"{titles.get(check_id, check_id)}:{mark}")
    return "  ".join(parts)


def _top_issue(entry: RouteEntry) -> str:
    for rule in sorted(REQUIREMENTS, key=lambda r: r.weight, reverse=True):
        result = entry.checks.get(rule.id)
        if result is not None and result.status == "fail":
            return result.message
    return "ok"


def render_terminal(result: MapResult, *, show_all: bool) -> str:
    """The human report: score, coverage, FIX FIRST / THEN / GOING FURTHER."""
    lines: list[str] = []
    counts = {"instrumented": 0, "partial": 0, "dark": 0, "exempt": 0}
    for entry in result.entries:
        counts[classify_observability(entry)] += 1

    scored = scored_entries(result.entries)
    lines.append(f"evlog map — observability score: {result.score}/100 ({result.grade})")
    lines.append(
        f"{len(scored)} entry points: {counts['instrumented']} instrumented, "
        f"{counts['partial']} partial, {counts['dark']} dark "
        f"({counts['exempt']} exempt)"
    )
    waived, waived_files = waived_checks(result.entries)
    if waived:
        lines.append(f"{waived} check(s) waived across {waived_files} file(s)")
    if result.unparsable:
        lines.append(f"warning: {len(result.unparsable)} file(s) failed to parse")
    lines.extend(f"warning: {warning}" for warning in result.warnings)

    failing = sorted(
        (e for e in scored if e.score < 100),
        key=lambda e: (e.sensitivity.level != "high", e.score),
    )
    if failing:
        lines.append("")
        lines.append("FIX FIRST")
        for entry in failing[:_FIX_FIRST_COUNT]:
            lines.append(
                f"  {entry.score:>3}  {_route_label(entry)}  "
                f"({_display(entry.file)}:{entry.handler.line})"
            )
            lines.append(f"       {_top_issue(entry)}")
        rest = failing[_FIX_FIRST_COUNT:]
        if rest:
            lines.append("")
            lines.append(f"THEN ({len(rest)} more)")
            by_issue: dict[str, list[RouteEntry]] = {}
            for entry in rest:
                by_issue.setdefault(_top_issue(entry), []).append(entry)
            for issue, group in sorted(by_issue.items(), key=lambda kv: -len(kv[1])):
                lines.append(f"  {len(group):>3}x  {issue}")

    suggestions = [
        (entry, check_id, res)
        for entry in scored
        for check_id, res in entry.suggestions.items()
        if res.status == "fail"
    ]
    if suggestions:
        lines.append("")
        lines.append(f"GOING FURTHER ({len(suggestions)} suggestion(s), no score impact)")
        by_id: dict[str, int] = {}
        for _, check_id, _res in suggestions:
            by_id[check_id] = by_id.get(check_id, 0) + 1
        for check_id, count in sorted(by_id.items(), key=lambda kv: -kv[1]):
            lines.append(f"  {count:>3}x  {check_id}")

    if show_all:
        lines.append("")
        for entry in sorted(scored, key=lambda e: e.score):
            lines.append(
                f"  {entry.score:>3}  {_route_label(entry)}  {_check_chips(entry)}  "
                f"({_display(entry.file)}:{entry.handler.line})"
            )
    return "\n".join(lines)


def to_json(result: MapResult) -> dict[str, object]:
    """The ``evlog.map.json`` contract — scores, entries, checks, sensitivity."""
    return {
        "score": result.score,
        "grade": result.grade,
        "framework": "fastapi",
        # How much surface the scan actually found. A 100/100 over an empty
        # map is not a pass — consumers gate on this too (``--min-entries``).
        "entryCount": len(scored_entries(result.entries)),
        "entries": [
            {
                "file": _display(entry.file),
                "line": entry.handler.line,
                "name": entry.handler.name,
                "kind": entry.handler.kind,
                "methods": list(entry.handler.methods),
                "path": entry.handler.route_path,
                "score": entry.score,
                "exempt": entry.exempt,
                "observability": classify_observability(entry),
                "sensitivity": {
                    "level": entry.sensitivity.level,
                    "label": entry.sensitivity.label,
                    "reasons": list(entry.sensitivity.reasons),
                },
                "checks": {
                    check_id: {"status": res.status, "message": res.message, "line": res.line}
                    for check_id, res in entry.checks.items()
                },
                "suggestions": {
                    check_id: {"status": res.status, "message": res.message, "line": res.line}
                    for check_id, res in entry.suggestions.items()
                },
            }
            for entry in result.entries
        ],
        "unparsable": [_display(p) for p in result.unparsable],
        "warnings": list(result.warnings),
    }


def render_github_summary(result: MapResult) -> str:
    """Markdown score summary for $GITHUB_STEP_SUMMARY."""
    counts = {"instrumented": 0, "partial": 0, "dark": 0, "exempt": 0}
    for entry in result.entries:
        counts[classify_observability(entry)] += 1
    scored = scored_entries(result.entries)
    failing = sorted(
        (e for e in scored if e.score < 100),
        key=lambda e: (e.sensitivity.level != "high", e.score),
    )
    waived, waived_files = waived_checks(result.entries)
    lines = [
        f"## Observability score: {result.score}/100 ({result.grade})",
        "",
        (
            f"{len(scored)} entry points — {counts['instrumented']} instrumented, "
            f"{counts['partial']} partial, {counts['dark']} dark, {counts['exempt']} exempt"
        ),
    ]
    if waived:
        lines += ["", f"{waived} check(s) waived across {waived_files} file(s)"]
    if failing:
        lines += ["", "| Score | Entry point | Top issue |", "|---|---|---|"]
        for entry in failing[:10]:
            label = _route_label(entry).strip()
            lines.append(
                f"| {entry.score} | `{label}` "
                f"({_display(entry.file)}:{entry.handler.line}) | {_top_issue(entry)} |"
            )
        if len(failing) > 10:
            lines.append(f"| … | {len(failing) - 10} more | see `evlog map --all` locally |")
    return "\n".join(lines)


def write_map_json(result: MapResult, path: Path) -> None:
    """Persist the map contract to ``evlog.map.json``."""
    path.write_text(json.dumps(to_json(result), indent=2) + "\n", encoding="utf-8")
