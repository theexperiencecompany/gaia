"""Discover entry points, run the rules, score the map.

The FastAPI adapter: route handlers are ``@router.<verb>`` / ``@app.<verb>``
functions anywhere under the scanned paths, workers are module-level async
functions in ``app/workers/tasks/``, and voice entry points are the LiveKit
callbacks named by the voice registry (``voice.collect_voice_registry``).
Scoring is evlog's: per-entry 100 minus
failed requirement weights; global score is the weighted average where
high-sensitivity handlers count double; grade bands at 90 / 70 / 50.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from directives import collect_suppressions, missing_reason, unknown_ids
from facts import FileFacts, HandlerFacts, collect_file_facts, repo_relative
from rules import REQUIREMENTS, RULE_IDS, CheckResult, RuleContext, run_rules
from sensitivity import Sensitivity, classify

_SKIP_SEGMENTS = ("__pycache__", "/tests/", "/migrations/", "/alembic/", "/.venv/", "/scripts/")
_WORKER_SEGMENT = "/workers/tasks/"

# Entry points with nothing to instrument — matches LoggingMiddleware._SKIP_PATHS.
_INFRA_ROUTE_PATHS = frozenset({"/health", "/metrics", "/favicon.ico"})

_GRADE_BANDS = ((90, "excellent"), (70, "good"), (50, "needs-work"))
_SENSITIVE_WEIGHT = 2.0


@dataclass
class RouteEntry:
    """One scored entry point."""

    handler: HandlerFacts
    file: Path
    sensitivity: Sensitivity
    checks: dict[str, CheckResult] = field(default_factory=dict)
    suggestions: dict[str, CheckResult] = field(default_factory=dict)
    score: int = 100
    exempt: bool = False


@dataclass
class MapResult:
    """The whole scan: scored entries plus the global score and grade."""

    entries: list[RouteEntry]
    score: int
    grade: str
    unparsable: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def iter_python_files(paths: list[Path]) -> list[Path]:
    """Expand paths to scannable ``.py`` files (tests, migrations, scripts excluded)."""
    out: set[Path] = set()
    for raw in paths:
        resolved = raw.resolve()
        if resolved.is_dir():
            candidates = resolved.rglob("*.py")
        elif resolved.suffix == ".py":
            candidates = iter([resolved])
        else:
            continue
        for file in candidates:
            posix = file.as_posix()
            if any(segment in posix for segment in _SKIP_SEGMENTS):
                continue
            if file.name.startswith("test_") or file.name.endswith("_test.py"):
                continue
            out.add(file)
    return sorted(out)


def _is_infra(handler: HandlerFacts) -> bool:
    """Exempt when ANY of the handler's stacked route paths is an infra path."""
    return any(path in _INFRA_ROUTE_PATHS for path in handler.route_paths)


def score_route(checks: dict[str, CheckResult]) -> int:
    """100 minus the weight of every failed requirement, floored at 0."""
    score = 100
    weights = {rule.id: rule.weight for rule in REQUIREMENTS}
    for check_id, result in checks.items():
        if result.status == "fail":
            score -= weights.get(check_id, 10)
    return max(0, score)


def weighted_score(items: list[tuple[int, str, bool]]) -> int:
    """Weighted average of ``(score, sensitivity_level, exempt)`` items.

    High-sensitivity entries count double; exempt entries are left out.
    Discovering nothing is NOT a perfect score — it is the scanner going
    blind (a broken scanner reports 100 over an empty map and everything
    stays green). Zero scorable entries scores 0 so the ``--min-score``
    gate catches discovery collapse without a hand-maintained entry-count
    floor. Shared by the global score and the per-file baseline comparison
    so the two can never disagree.
    """
    scored = [(score, level) for score, level, exempt in items if not exempt]
    if not scored:
        return 0
    total_weight = 0.0
    weighted_sum = 0.0
    for score, level in scored:
        weight = _SENSITIVE_WEIGHT if level == "high" else 1.0
        total_weight += weight
        weighted_sum += score * weight
    return round(weighted_sum / total_weight)


def scored_entries(entries: list[RouteEntry]) -> list[RouteEntry]:
    """The entry points the score is computed over — exempt ones are not scored.

    The single definition of "how much surface did discovery actually find",
    shared by the report, the JSON contract, and the ``--min-entries`` gate.
    """
    return [entry for entry in entries if not entry.exempt]


def waived_checks(entries: list[RouteEntry]) -> tuple[int, int]:
    """``(checks waived, files they sit in)`` across the scan."""
    waived = [entry for entry in entries for result in entry.checks.values() if result.suppressed]
    return len(waived), len({entry.file for entry in waived})


def score_global(entries: list[RouteEntry]) -> int:
    """Weighted average of entry scores — high-sensitivity entries count double."""
    return weighted_score(
        [(entry.score, entry.sensitivity.level, entry.exempt) for entry in entries]
    )


def grade_from_score(score: int) -> str:
    """Grade band for a score, at 90 / 70 / 50."""
    for threshold, grade in _GRADE_BANDS:
        if score >= threshold:
            return grade
    return "at-risk"


def classify_observability(entry: RouteEntry) -> str:
    """How much of this entry point the map can actually see."""
    if entry.exempt:
        return "exempt"
    wide = entry.checks.get("wide-event")
    context = entry.checks.get("context")
    wide_ok = wide is not None and wide.status == "pass"
    # A suppressed context check is waived, not covered — that entry is
    # "partial", so the headline coverage number cannot absorb waivers.
    context_ok = context is None or context.status == "pass"
    if wide_ok and context_ok:
        return "instrumented"
    if wide_ok:
        return "partial"
    return "dark"


def collect_worker_registry(worker_module: Path) -> frozenset[str]:
    """Names of ARQ tasks actually registered — imported by ``app/worker.py``.

    Only registered tasks are worker entry points; other module-level async
    functions in ``workers/tasks/`` are helpers running inside a registered
    task's ``wide_task()`` boundary, and scoring them would be a false alarm.
    """

    tree = ast.parse(worker_module.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith("app.workers.tasks"):
                names.update(alias.name for alias in node.names)
    if not names:
        raise ValueError(f"no worker tasks found in {worker_module} — registry moved?")
    return frozenset(names)


def scan(
    paths: list[Path],
    canonical_fields: frozenset[str],
    worker_registry: frozenset[str],
    voice_registry: dict[str, frozenset[str]],
    router_mounts: dict[str, str],
) -> MapResult:
    """Discover, classify, and score every entry point under ``paths``."""
    entries: list[RouteEntry] = []
    unparsable: list[Path] = []
    warnings: list[str] = []

    for file in iter_python_files(paths):
        source = file.read_text(encoding="utf-8")
        is_worker = _WORKER_SEGMENT in file.as_posix()
        file_facts: FileFacts | None = collect_file_facts(
            file,
            source,
            is_worker_module=is_worker,
            voice_entries=voice_registry.get(file.as_posix(), frozenset()),
            mount_prefix=router_mounts.get(repo_relative(file), ""),
        )
        if file_facts is None:
            unparsable.append(file)
            continue
        if not file_facts.handlers:
            continue
        suppressions = collect_suppressions(source)
        for bad in unknown_ids(suppressions, RULE_IDS):
            warnings.append(
                f"{file}:{bad.declared_at} disables {bad.check_id!r}, "
                "which is not a check evlog map runs"
            )
        for reasonless in missing_reason(suppressions):
            warnings.append(
                f"{file}:{reasonless.declared_at} disables a check with no "
                "'-- <reason>' — rejected, the check still applies"
            )
        for handler in file_facts.handlers:
            if handler.kind == "worker" and handler.name not in worker_registry:
                continue
            if handler.kind == "worker":
                # worker.py wraps every registered task in arq_task, the
                # wide-event + metrics envelope — the boundary is provided by
                # the wrapper, not by a wide_task() inside the task file.
                handler.has_boundary = True
            sensitivity = classify(handler, file_facts)
            entry = RouteEntry(handler=handler, file=file, sensitivity=sensitivity)
            if _is_infra(handler):
                entry.exempt = True
                entries.append(entry)
                continue
            ctx = RuleContext(
                handler=handler,
                file_facts=file_facts,
                sensitivity=sensitivity,
                canonical_fields=canonical_fields,
            )
            results = run_rules(ctx, suppressions)
            entry.checks = results.checks
            entry.suggestions = results.suggestions
            entry.score = score_route(results.checks)
            entries.append(entry)

    score = score_global(entries)
    return MapResult(
        entries=entries,
        score=score,
        grade=grade_from_score(score),
        unparsable=unparsable,
        warnings=warnings,
    )
