"""Tear Opik down and rebuild it from the journals, in one re-runnable command.

The journals on disk are the source of truth; Opik is a derived view. So the
honest repair for a polluted Opik is not a surgical patch — it is to delete the
derived view and rebuild it, which is also the only way to be sure what is left
is trustworthy.

Three things make this safe to actually run:

* ``--dry-run`` reports exactly what would be deleted and written, and touches
  nothing;
* every stage is followed by :mod:`.ingest_check`, which reads the result back
  out of Opik and aborts the next stage if the numbers are impossible;
* ``--pilot`` ingests one small suite first and checks it before committing to
  the full rebuild, so a mistake costs one suite rather than everything.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import cast

from . import ingest_check, opiksink
from .journal import RunJournal
from .providers import EvalConfig
from .runner import RUNS_DIR, SUITE_REGISTRY, Suite
from .seed import SEEDABLE_STATUSES, seed


def _project_of(entry: Callable[[EvalConfig], Suite]) -> str:
    """The Opik project a registered suite writes to.

    ``SUITE_REGISTRY`` is annotated as a factory callable but actually holds the
    Suite *classes*, which carry ``project`` as a class attribute. Narrowing once
    here keeps the assumption in a single place; the real fix is to annotate the
    registry as ``dict[str, type[Suite]]`` in ``runner.py``.
    """
    return str(cast(type[Suite], entry).project)


#: Pilot stage 1: the smallest suite there is, so a broken rebuild is caught on
#: three cases instead of two thousand.
PILOT_FIRST_SUITE = "smoke"

#: Pilot stage 2: the suite whose numbers were most obviously wrong, and the one
#: with enough volume for a per-case token figure to mean something.
PILOT_SECOND_SUITE = "longmemeval"
PILOT_SECOND_LIMIT = 10


@dataclass(frozen=True)
class RunInfo:
    run_id: str
    suite: str
    project: str
    cases: int
    excluded: str | None
    status: str = "finished"


def survey(runs_dir: Path = RUNS_DIR) -> list[RunInfo]:
    """Every run on disk that a seed could ingest, with its case count."""
    out: list[RunInfo] = []
    for run_dir in sorted(runs_dir.iterdir()):
        meta_file = run_dir / "run.json"
        if not run_dir.is_dir() or not meta_file.exists():
            continue
        meta = json.loads(meta_file.read_text())
        suite_name = str(meta.get("suite") or "")
        suite = SUITE_REGISTRY.get(suite_name)
        if suite is None:
            continue
        cases = {
            str(record["case_id"])
            for record in RunJournal(runs_dir, run_dir.name).records()
            if record.get("status") in SEEDABLE_STATUSES
        }
        out.append(
            RunInfo(
                run_id=run_dir.name,
                suite=suite_name,
                project=_project_of(suite),
                cases=len(cases),
                excluded=meta.get("excluded"),
                status=str(meta.get("status") or "finished"),
            )
        )
    return out


def ingestable(runs: list[RunInfo]) -> list[RunInfo]:
    """Runs whose measurements may be aggregated.

    A run marked ``excluded`` in its ``run.json`` recorded numbers we already
    know are wrong. Seeding it puts those numbers back into the totals — which
    is precisely how a project came to report 461 million tokens.

    A run still ``running`` is skipped too: it appends between the seed and the
    read-back, so the reconciliation is off by however many cases landed in
    that window — a moving target can never verify. It seeds on its next
    finished (or aborted) ingest.
    """
    return [run for run in runs if not run.excluded and run.status != "running"]


def suite_projects() -> dict[str, str]:
    return {name: _project_of(suite) for name, suite in SUITE_REGISTRY.items()}


def teardown(base_url: str, *, dry_run: bool) -> list[str]:
    """Delete every ``gaia-*`` project, traces and all.

    Deleting the projects rather than their traces is not a shortcut: a single
    trace delete costs ~3.5s on this backend, so evicting one polluted project's
    25,144 traces one by one would take a day.
    """
    names = ingest_check.project_names(base_url)
    if dry_run:
        for name in names:
            print(
                f"[ingest] would DELETE project {name:<20} "
                f"({ingest_check.trace_count(base_url, name)} traces)"
            )
        return names
    client = opiksink.client("default")
    found = client.rest_client.projects.find_projects(page=1, size=200)
    ids = [p.id for p in found.content if p.name in set(names)]
    if ids:
        client.rest_client.projects.delete_projects_batch(ids=ids)
    for name in names:
        print(f"[ingest] deleted project {name}")
    # Datasets are workspace-level, so deleting the projects leaves them behind
    # as orphans that no project-scoped lookup can find — which deadlocked every
    # later finalize on a 404-then-409.
    dropped = opiksink.delete_datasets([f"{name}-cases" for name in names])
    print(f"[ingest] deleted {len(dropped)} orphaned dataset(s)")
    return names


def verify(
    base_url: str, runs_dir: Path = RUNS_DIR, only_projects: set[str] | None = None
) -> tuple[bool, str]:
    """Read projects back out of Opik and judge whether they are believable.

    ``only_projects`` scopes the judgement to what a stage just wrote. A pilot
    stage that verified everything could never pass while the projects it has
    not rebuilt yet are still dirty — it would abort the rebuild it exists to
    de-risk.
    """
    projects = suite_projects()
    expectations = ingest_check.journal_expectations(runs_dir, projects, only_projects)
    unversioned = ingest_check.journal_missing_app_version(runs_dir, projects, only_projects)
    # Drive from what the journals expect, not from what Opik happens to hold.
    # Iterating the backend's project list meant a stage whose seed failed
    # outright had nothing to inspect and was therefore reported as passing —
    # the same "absence reads as success" defect this check exists to catch.
    names = sorted(set(ingest_check.project_names(base_url)) | set(expectations))
    if only_projects is not None:
        names = [name for name in names if name in only_projects]
    all_facts = [ingest_check.read_project(base_url, name) for name in names]
    findings = [
        finding
        for facts in all_facts
        for finding in ingest_check.check(
            facts, expectations.get(facts.name), unversioned.get(facts.name, 0)
        )
    ]
    return not findings, ingest_check.render(all_facts, findings, unversioned)


def _stage(
    cfg: EvalConfig,
    base_url: str,
    label: str,
    run_ids: set[str] | None,
    projects: set[str] | None,
    runs_dir: Path,
    *,
    dry_run: bool,
) -> bool:
    count = "every run" if run_ids is None else f"{len(run_ids)} run(s)"
    print(f"\n[ingest] === stage: {label} — {count} ===")
    if dry_run:
        print(f"[ingest] would seed {count}")
        return True
    seed(cfg, runs_dir, only_runs=run_ids)
    ok, report = verify(base_url, runs_dir, projects)
    print(report)
    if not ok:
        print(f"[ingest] stage {label!r} FAILED verification — stopping before the next stage")
    return ok


def rebuild(
    cfg: EvalConfig,
    *,
    runs_dir: Path = RUNS_DIR,
    dry_run: bool = False,
    pilot: bool = False,
    skip_teardown: bool = False,
) -> int:
    """Delete the gaia projects and rebuild them from the journals.

    Returns a process exit code: non-zero when any stage's data failed to verify,
    so this can gate a script instead of being read by eye.
    """
    base_url = ingest_check.api_base(os.environ["OPIK_URL_OVERRIDE"])
    runs = survey(runs_dir)
    usable = ingestable(runs)
    excluded = [run for run in runs if run.excluded]

    print(
        f"[ingest] {len(runs)} runs on disk · {len(usable)} ingestable · {len(excluded)} excluded"
    )
    for run in excluded:
        print(f"[ingest]   skipping {run.run_id} ({run.cases} cases): excluded — {run.excluded}")
    if dry_run:
        by_project: dict[str, int] = {}
        for run in usable:
            by_project[run.project] = by_project.get(run.project, 0) + run.cases
        for project, cases in sorted(by_project.items()):
            print(f"[ingest] would write ~{cases:>5} case traces into {project}")

    if not skip_teardown:
        teardown(base_url, dry_run=dry_run)

    def stage_for(suite: str, limit: int | None = None) -> tuple[set[str], set[str]]:
        runs_in = [
            r for r in sorted(usable, key=lambda r: r.run_id, reverse=True) if r.suite == suite
        ]
        chosen = runs_in[:limit] if limit else runs_in
        return {r.run_id for r in chosen}, {r.project for r in chosen}

    stages: list[tuple[str, set[str], set[str]]] = []
    if pilot:
        first_runs, first_projects = stage_for(PILOT_FIRST_SUITE)
        second_runs, second_projects = stage_for(PILOT_SECOND_SUITE, PILOT_SECOND_LIMIT)
        stages.append((f"pilot 1 · {PILOT_FIRST_SUITE}", first_runs, first_projects))
        stages.append((f"pilot 2 · {PILOT_SECOND_SUITE}", second_runs, second_projects))
    stages.append(("full", {r.run_id for r in usable}, {r.project for r in usable}))

    for label, run_ids, projects in stages:
        if not run_ids:
            print(f"[ingest] stage {label!r}: no runs on disk, skipping")
            continue
        if not _stage(cfg, base_url, label, run_ids, projects, runs_dir, dry_run=dry_run):
            return 1
    return 0
