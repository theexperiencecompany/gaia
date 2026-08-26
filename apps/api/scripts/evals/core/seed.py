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
from typing import Any

from . import opiksink
from .journal import RunJournal
from .providers import EvalConfig, price_book
from .runner import RUNS_DIR, SUITE_REGISTRY
from .types import CaseTrace, PriceBook

# ``errored`` belongs here even though it carries no score: the live run logs
# those traces, so omitting them would make a backfill disagree with the run it
# is replaying — and a crashed case is exactly what you go to Opik to look at.
SEEDABLE_STATUSES = {"passed", "failed", "errored"}

#: Suites whose pre-fix journals cannot be trusted for tokens, per the token
#: accounting audit. Three differenced a *shared* run meter while 3-14 cases ran
#: concurrently, so each case was credited with its neighbours' spend; two never
#: measured at all and inferred tokens from string length; one journalled zero.
#:
#: This is a fallback for journals written before ``tokens.source`` existed. A
#: record that carries the field is believed over this list, so the list retires
#: itself as suites are re-run rather than becoming a permanent second source of
#: truth. ``safety``, ``comms`` and ``quality`` are absent deliberately: they read
#: provider-reported usage per case, which is the mechanism we trust.
UNMETERED_LEGACY_SUITES = frozenset(
    {"capability", "memory", "longmemeval", "regression", "gaia_bench", "hil", "smoke"}
)

#: Suites whose pre-fix journals ARE trustworthy for tokens: they read the usage
#: the provider reported, per case, off the API's response frames. Instrumenting
#: the live API settled it — usage arrives once per turn and is per-turn, not
#: cumulative, so summing across turns is correct. Their large numbers are real
#: spend rather than a counting bug, and dropping them would throw away the only
#: sound cost data we have.
METERED_LEGACY_SUITES = frozenset({"quality", "comms", "safety"})

#: What "this record was never actually measured" looks like. Mirrors the bound
#: :mod:`.ingest_check` publishes on, so the seeder and the checker cannot
#: disagree about which records count as unmeasured.
UNMEASURED_BELOW_TOKENS = 500
UNMEASURED_BELOW_SECONDS = 2.0

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
                _seed_project(project, grouped[project], prices, runs_dir, reset=reset)
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
    runs_dir: Path,
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
            _with_adopted_rescore(
                _with_resolved_token_source(record, meta.suite if meta else ""), runs_dir, run_id
            ),
            prices,
            suite=meta.suite if meta else "",
            app_version=meta.app_version if meta else "",
        )
        for run_id in run_ids
        for journal in [RunJournal(runs_dir, run_id)]
        for meta in [journal.load_meta()]
        for record in journal.records()
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


_RESCORE_CACHE: dict[Path, dict[str, dict[str, Any]]] = {}


def _with_adopted_rescore(record: dict[str, Any], runs_dir: Path, run_id: str) -> dict[str, Any]:
    """Adopt a rescore sibling's verdict for this case, if one exists.

    Re-scoring never rewrites the append-only journal; it records corrected
    verdicts in ``rescore.json`` beside it. Without adoption those corrections
    stayed on disk while Opik and every dashboard kept showing verdicts the
    gate fixes had already overturned. Adoption is visible: the trace metadata
    gains ``rescored: true`` so a reader can tell a re-graded verdict from an
    original one.
    """
    sibling = runs_dir / run_id / "rescore.json"
    if sibling not in _RESCORE_CACHE:
        by_case: dict[str, dict[str, Any]] = {}
        if sibling.exists():
            for entry in json.loads(sibling.read_text()).get("cases", []):
                by_case[str(entry["case_id"])] = entry
        _RESCORE_CACHE[sibling] = by_case
    entry = _RESCORE_CACHE[sibling].get(str(record.get("case_id")))
    if entry is None or entry["was"] == entry["now"]:
        return record
    return {
        **record,
        "status": entry["now"],
        "scores": entry.get("new_scores") or record.get("scores"),
        "rescored": True,
    }


def _with_resolved_token_source(record: dict[str, Any], suite: str) -> dict[str, Any]:
    """Label a pre-fix record's token provenance so cost can be withheld from it.

    A journal written before ``tokens.source`` existed says nothing about how its
    numbers were obtained, and for seven suites they were obtained wrongly. The
    accuracy in those runs is sound, so they are still worth ingesting — the
    tokens and the cost derived from them are not, and are dropped rather than
    published at a plausible-looking wrong value.
    """
    tokens = record.get("tokens") or {}
    if tokens.get("source"):
        return record
    if suite in METERED_LEGACY_SUITES:
        # The suite list says the MECHANISM is trustworthy; it cannot say that
        # every record actually got a reading. Quality's runs split cleanly on
        # the day the usage-frame wiring landed — every run before it recorded
        # ~20 tokens for cases that worked for 6-21 seconds, every run after it
        # measured properly. A record with no measurement is `none` whatever its
        # suite, so the two rules compose instead of one overriding the other.
        measured = int(tokens.get("input", 0)) + int(tokens.get("output", 0))
        worked = float(record.get("duration_s") or 0) >= UNMEASURED_BELOW_SECONDS
        resolved = "none" if worked and measured < UNMEASURED_BELOW_TOKENS else "metered"
    elif suite in UNMETERED_LEGACY_SUITES:
        resolved = "unmetered"
    else:
        # A suite nobody has adjudicated. Untrusted by default: a new suite
        # silently inheriting "believe its numbers" is how this started.
        resolved = "unknown"
    return {**record, "tokens": {**tokens, "source": resolved}}


class LegacyTracesPresentError(RuntimeError):
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
        raise LegacyTracesPresentError(
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
