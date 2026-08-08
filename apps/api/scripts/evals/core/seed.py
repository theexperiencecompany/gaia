"""Backfill Opik from the run journals.

The journals are the source of truth; Opik is a derived view. Seeding replays
every terminal case of every run into its suite's project, and is:

* **idempotent** — a case already present *for that run* is skipped, so the same
  case legitimately re-run in a later run still lands as its own trace;
* **self-healing** — duplicate traces left by earlier partial seeds are pruned
  down to one per ``CaseTrace.key``;
* **resilient** — a record that fails to write is counted and reported, never
  allowed to abort the rest of the backfill.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import opiksink
from .journal import RunJournal
from .providers import EvalConfig, price_book
from .runner import RUNS_DIR, SUITE_REGISTRY
from .types import CaseTrace, PriceBook

# ``errored`` belongs here even though it carries no score: the live run logs
# those traces, so omitting them would make a backfill disagree with the run it
# is replaying — and a crashed case is exactly what you go to Opik to look at.
SEEDABLE_STATUSES = {"passed", "failed", "errored"}

# Descriptions belong to the Opik project rather than to a suite, because a
# project can be fed by more than one suite (regression writes into capability).
PROJECT_DESCRIPTIONS: dict[str, str] = {
    "gaia-memory": (
        "Memory engine benchmark — 45 scenarios across 10 weakness categories "
        "(temporal, contradiction, distractor, abstention, knowledge graph). "
        "In-process against the real memory pipeline."
    ),
    "gaia-longmemeval": (
        "LongMemEval oracle (500 questions) — extraction, multi-session, "
        "temporal reasoning, knowledge update and abstention abilities, "
        "graded by an LLM judge from a different model family."
    ),
    "gaia-capability": (
        "Can GAIA do X? — tool-call cases across todos, tracked todos, "
        "reminders, workflows, web, multi-turn, gmail triage and memory recall, "
        "including the hard tier (composition, conflict, ambiguity, injection). "
        "Also receives the deterministic regression gate."
    ),
    "gaia-quality": (
        "Does GAIA sound human and behave well? — live-API transcripts scored on "
        "bubble structure, tool cards, suggestions and OpenUI fences, plus a "
        "rubric judge."
    ),
    "gaia-bench": (
        "Official GAIA benchmark (2023 validation, 165 questions) — web research "
        "with the leaderboard's exact-match scorer, broken out by level L1/L2/L3."
    ),
    "gaia-comms": (
        "Does the comms agent route and stay honest? — the user-facing agent that "
        "holds no work tools: delegating real work vs handling chat itself, asking "
        "instead of guessing, carrying context across turns, never fabricating."
    ),
    "gaia-safety": (
        "Is GAIA safe under adversarial input? — chat-level prompt injection, "
        "instruction override, exfiltration via tool args, jailbreak framings and "
        "moderation, plus refusal consistency and over-refusal of benign requests."
    ),
    "gaia-hil": (
        "Human-in-the-loop and comprehension — the real approval gate end to end "
        "(pause, approve/deny, resumed end state) plus underspecified, "
        "contradictory and multi-step requests needing confirmation before acting."
    ),
    "gaia-smoke": "Harness plumbing only — provider rotation, journal and report wiring.",
}


def seed(
    cfg: EvalConfig,
    runs_dir: Path = RUNS_DIR,
    *,
    reset: bool = False,
    only_runs: set[str] | None = None,
) -> None:
    """Replay run journals into Opik. Safe to run repeatedly.

    Every write is an upsert keyed on the case's identity, so a re-seed refreshes
    what is already there rather than duplicating or skipping it. ``reset``
    additionally deletes a project's existing case traces first, which is only
    needed to evict traces whose source journal is gone.

    ``only_runs`` limits the backfill to named run ids — the pilot path, where
    one small suite is ingested and checked before the rest follows.
    """
    prices = price_book(cfg)
    grouped = _group_runs_by_project(runs_dir, only_runs)
    if not grouped:
        print(f"[seed] no runs with a registered suite under {runs_dir}")
        return
    try:
        for project in sorted(grouped):
            try:
                _seed_project(project, grouped[project], prices, reset=reset)
            except Exception as e:
                print(f"[seed] {project} aborted: {type(e).__name__}: {e}")
    finally:
        opiksink.close_clients()


def _group_runs_by_project(
    runs_dir: Path, only_runs: set[str] | None = None
) -> dict[str, list[str]]:
    """Run ids per Opik project, resolved through the suite registry.

    The registry holds the suite classes, so the project name comes from the
    same declaration the live run loop uses — never a second hardcoded map.
    """
    grouped: dict[str, list[str]] = {}
    for run_dir in sorted(runs_dir.iterdir()):
        meta_file = run_dir / "run.json"
        if not run_dir.is_dir() or not meta_file.exists():
            continue
        if only_runs is not None and run_dir.name not in only_runs:
            continue
        suite_name = json.loads(meta_file.read_text()).get("suite", "")
        suite = SUITE_REGISTRY.get(suite_name)
        if suite is None:
            print(f"[seed] skip {run_dir.name}: suite '{suite_name}' is not registered")
            continue
        grouped.setdefault(suite.project, []).append(run_dir.name)
    return grouped


def _seed_project(
    project: str,
    run_ids: list[str],
    prices: PriceBook,
    *,
    reset: bool = False,
) -> None:
    """Write every seedable record of every run. Always writes, never queries.

    Idempotency comes from the trace id being derived from the case's identity
    (:func:`opiksink.trace_id_for`), so re-writing a case updates its row instead
    of adding one. The previous design asked Opik what already existed and
    skipped those — which duplicated any trace whose first write had not yet
    become queryable, and could never refresh a trace whose contents had changed.
    Writing unconditionally is both simpler and more correct.
    """
    _apply_description(project)
    if reset:
        purged = opiksink.purge_case_traces(project)
        print(f"[seed] {project}: purged {purged} existing case traces")

    traces = [
        CaseTrace.from_record(
            run_id,
            record,
            prices,
            suite=meta.suite if meta else "",
            app_version=meta.app_version if meta else "",
        )
        for run_id in run_ids
        for meta in [RunJournal(RUNS_DIR, run_id).load_meta()]
        for record in RunJournal(RUNS_DIR, run_id).records()
        if record.get("status") in SEEDABLE_STATUSES
    ]
    _refuse_to_double(project, traces)

    written = failed = 0
    for trace in traces:
        try:
            opiksink.log_case_trace(project, trace)
            written += 1
        except Exception as e:
            failed += 1
            print(f"[seed] {project}/{trace.run_id}/{trace.case_id}: {type(e).__name__}: {e}")
    opiksink.flush(project)
    print(f"[seed] {project:<18} runs={len(run_ids):<3} {written} written · {failed} failed")


class LegacyTracesPresent(RuntimeError):
    """A seed would duplicate traces instead of updating them."""


def _refuse_to_double(project: str, traces: list[CaseTrace]) -> None:
    """Abort rather than silently double a project's totals.

    Upsert-by-derived-id only updates traces that were themselves written with a
    derived id. A trace written by an older build carries a random one, so
    seeding on top of it INSERTS a second copy — every count, cost and token
    total doubles, and nothing in the output says so.

    This is the loud half of the fix. Idempotency is no longer defeatable by a
    metadata rename (the id comes from the journal, never from Opik), but it is
    still defeatable by legacy rows, and that has to fail rather than pass
    quietly. `ingest` tears the project down first, so it never trips.
    """
    expected = {opiksink.trace_id_for(project, trace) for trace in traces}
    legacy = opiksink.legacy_case_traces(project, expected)
    if legacy:
        raise LegacyTracesPresent(
            f"{project}: {legacy} case trace(s) predate derived ids, so seeding would add "
            f"duplicates rather than update them. Rebuild the project instead: "
            f"`python -m scripts.evals ingest` (or seed --reset for this project alone)."
        )


MAX_DESCRIPTION = 255


def _apply_description(project: str) -> None:
    """Set the project blurb. Never fatal — the traces are the point, and a
    rejected description must not cost us a whole project's data (a 255-char
    limit once aborted three projects mid-seed)."""
    description = PROJECT_DESCRIPTIONS.get(project)
    if description is None:
        print(f"[seed] {project}: no description registered in PROJECT_DESCRIPTIONS")
        return
    if len(description) > MAX_DESCRIPTION:
        print(
            f"[seed] {project}: description is {len(description)} chars, "
            f"over Opik's {MAX_DESCRIPTION} limit — shorten it in PROJECT_DESCRIPTIONS"
        )
        return
    try:
        opiksink.set_description(project, description)
    except Exception as e:
        print(f"[seed] {project}: description not set: {type(e).__name__}: {e}")
