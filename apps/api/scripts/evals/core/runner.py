"""The run loop: journal → provider rotation → run → score → append → finalize."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
import os
from pathlib import Path
import subprocess
import time
from typing import Any
import uuid

from . import baseline, faults, opiksink
from .cost import EvalCostTracker
from .invariants import check_records
from .journal import RunJournal, RunMeta
from .providers import (
    EvalConfig,
    ProviderConfig,
    health_check,
    pin_settings,
    price_book,
    rotation_chain,
)
from .report import write_report
from .scorers import judge_env
from .types import GATE_PASS_THRESHOLD, Case, CaseRun, CaseTrace, PriceBook, ProviderError

RUNS_DIR = Path(__file__).resolve().parent.parent / "runs"

_MARKERS = {"passed": "✓", "failed": "✗", "errored": "!"}

SUITE_REGISTRY: dict[str, Callable[[EvalConfig], Suite]] = {}


def register_suite(
    name: str,
) -> Callable[[Callable[[EvalConfig], Suite]], Callable[[EvalConfig], Suite]]:
    def decorator(factory: Callable[[EvalConfig], Suite]) -> Callable[[EvalConfig], Suite]:
        SUITE_REGISTRY[name] = factory
        return factory

    return decorator


class Suite:
    """Interface implemented by every suite module."""

    name: str = "?"
    project: str = "gaia-memory"
    label: str = "?"

    def load_cases(self, cfg: EvalConfig) -> list[Case]:
        raise NotImplementedError

    def score(self, case: Case, run: CaseRun) -> dict[str, float]:
        raise NotImplementedError

    def transport(
        self, case: Case, cfg: EvalConfig, tracker: EvalCostTracker, provider: ProviderConfig
    ) -> Awaitable[CaseRun]:
        raise NotImplementedError

    def finalize_scorers(self, cfg: EvalConfig) -> list[object]:
        del cfg
        return []


class RunOptions:
    def __init__(
        self,
        *,
        suite: str,
        resume: str | None = None,
        limit: int | None = None,
        from_case: str | None = None,
        only: list[str] | None = None,
        only_failed: bool = False,
        providers: list[str] | None = None,
        exclude: list[str] | None = None,
        max_usd: float | None = None,
        sim: bool = False,
        no_finalize: bool = False,
        tags: list[str] | None = None,
        concurrency: int = 1,
        rebaseline: bool = False,
    ) -> None:
        self.suite = suite
        self.resume = resume
        self.limit = limit
        self.from_case = from_case
        self.only = only or []
        self.only_failed = only_failed
        self.providers = providers
        self.exclude = exclude or []
        self.max_usd = max_usd
        self.sim = sim
        self.no_finalize = no_finalize
        self.tags = tags or []
        self.concurrency = max(1, concurrency)
        self.rebaseline = rebaseline


def select_cases(cases: list[Case], opts: RunOptions, journal: RunJournal) -> list[Case]:
    """Decide which of the suite's cases this run executes.

    Kept whole and apart from the run loop because the selection is where every
    "the run did nothing and said nothing" defect has come from — and because
    testing it against a journal costs nothing, while testing it through
    ``run_suite`` costs a live API and a model bill.
    """
    if opts.only:
        # --from is an ordered cursor, so it cannot pick out a case that sorts
        # after cases in an earlier data file. --only names cases outright, and
        # fails loudly on a typo rather than silently running nothing.
        wanted = set(opts.only)
        cases = [c for c in cases if c.id in wanted]
        unknown = sorted(wanted - {c.id for c in cases})
        if unknown:
            raise SystemExit(f"--only: no such case id(s): {', '.join(unknown)}")
    if opts.from_case:
        cases = [c for c in cases if c.id >= opts.from_case]

    # Journal-based selection is ONE decision, not a chain of filters that empty
    # each other out. --only-failed used to run after --resume had already
    # removed every finished case, so it selected nothing; without --resume the
    # journal was new, so it also selected nothing. It silently did nothing in
    # both modes, which is why every retry has been a full re-run.
    if opts.only_failed:
        latest = journal.latest_per_case()
        if not latest:
            raise SystemExit("--only-failed needs an existing run to read: pass --resume <run-id>")
        failed = {cid for cid, rec in latest.items() if rec.get("status") == "failed"}
        if not failed:
            raise SystemExit("--only-failed: that run has no failed cases")
        cases = [c for c in cases if c.id in failed]
    elif opts.resume:
        cases = [c for c in cases if not journal.has_terminal(c.id)]

    if opts.limit is not None:
        cases = cases[: opts.limit]
    return cases


async def run_suite(cfg: EvalConfig, opts: RunOptions) -> Path:
    factory = SUITE_REGISTRY.get(opts.suite)
    if factory is None:
        raise SystemExit(
            f"unknown suite '{opts.suite}'. Available: {', '.join(sorted(SUITE_REGISTRY))}"
        )
    suite = factory(cfg)

    order = rotation_chain(cfg, opts.providers, opts.exclude)
    if not order:
        raise SystemExit("no providers available (all excluded or unknown)")

    run_id = (
        opts.resume
        or f"{opts.suite}-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    )
    # Checked before RunJournal, which creates the directory unconditionally: a
    # mistyped run id used to produce an empty run dir with no run.json, and the
    # first read of its metadata then died on `NoneType has no attribute` pages
    # later, in a place that says nothing about the typo.
    if opts.resume is not None and not (RUNS_DIR / opts.resume / "run.json").exists():
        raise SystemExit(f"--resume: no run '{opts.resume}' under {RUNS_DIR}")
    journal = RunJournal(RUNS_DIR, run_id)
    if opts.resume is None:
        journal.create_meta(
            RunMeta(
                run_id=run_id,
                suite=suite.name,
                started_at=datetime.now(UTC).isoformat(timespec="seconds"),
                provider_order=order,
                tags=opts.tags,
                app_version=_app_version(),
                extra={"sim": opts.sim},
            )
        )
    else:
        # A resumed run is live again. Leaving the stale terminal status in
        # place made a mid-append run look finished to ingest, whose read-back
        # then chased a moving target and failed on a phantom mismatch.
        journal.update_meta(status="running")

    tracker = EvalCostTracker(cfg.providers, opts.max_usd or cfg.default_max_usd)

    # Boot-time provider health: dead providers are skipped for the whole run.
    healthy: list[str] = []
    skipped: dict[str, str] = {}
    for name in order:
        provider = cfg.providers[name]
        check = health_check(provider)
        if check.ok:
            healthy.append(name)
        else:
            skipped[name] = check.reason
            print(f"[health] skipping {name}: {check.reason}")
    if not healthy:
        raise SystemExit(f"no healthy providers: {skipped}")

    cases = select_cases(suite.load_cases(cfg), opts, journal)

    print(f"[run] {run_id} · suite={suite.name} · providers={healthy} · cases={len(cases)}")

    prices = price_book(cfg)
    # Read once: a resumed run's version is the one the journal recorded, not
    # whatever the working tree describes as now.
    app_version = _require_meta(journal).app_version

    def _sink_deferred() -> bool:
        return os.environ.get("EVALS_DEFER_OPIK_SINK", "") == "1"

    # Records appended during THIS invocation, kept apart from the journal's
    # full history: a resumed or --only-failed run appends a second attempt for
    # cases the journal already holds, and the publish invariants must validate
    # exactly what this run measured against what this run metered — the same
    # scope on both sides.
    run_records: list[dict[str, Any]] = []

    def record_case(
        case: Case, run: CaseRun, scores: dict[str, float], status: str, error: str | None
    ) -> None:
        """Journal a finished case and mirror it into Opik — including failures,
        which are exactly the cases worth looking at in the UI."""
        source = _attribute_tokens(run, tracker, case.id)
        record = _record(case, run, scores, status, error, source)
        journal.append(record)
        run_records.append(record)
        # The live sink serialises and compresses every transcript on SDK
        # background threads DURING the run — on long-context suites that burned
        # more CPU than the cases themselves. `evals seed` rebuilds the same
        # traces from the journal afterwards, so deferring loses nothing.
        if not _sink_deferred():
            _log_trace(suite.project, run_id, record, prices, suite.name, app_version)

    aborted: str | None = None
    run_status = "finished"

    # Both modes run inside this one try, so an interrupt is recorded the same
    # way whichever it was. A concurrent run used to return from its own branch
    # before the handler existed: Ctrl-C on one left the traces unflushed and
    # `run.json` saying "running" forever, which resume, sweep and ingest all
    # read as a run still in flight.
    try:
        # Concurrency pins ONE provider for the whole run, deliberately.
        # pin_settings mutates a shared settings singleton and resets the lazy
        # provider, so two cases pinning different lanes would race — and
        # re-pinning mid-flight is the same engine-reset that turned one
        # Postgres blip into 76 fabricated zeros. Rotation is therefore a
        # sequential-only feature; a pinned run that loses its provider aborts
        # rather than silently continuing on another.
        if opts.concurrency > 1:
            pinned_name = healthy[0]
            pin_settings(cfg.providers[pinned_name])
            tracker.set_provider(pinned_name)
            print(
                f"[run] concurrency={opts.concurrency} · provider pinned to {pinned_name} "
                f"(rotation disabled: the app's provider settings are process-global)"
            )
            aborted = await _run_cases_concurrently(
                cases,
                suite,
                cfg,
                opts,
                tracker,
                cfg.providers[pinned_name],
                pinned_name,
                record_case,
            )
            if aborted:
                print(f"\n[abort] {aborted}")
        else:
            aborted = await _run_cases_sequentially(
                cases, suite, cfg, tracker, journal, healthy, record_case
            )
    except KeyboardInterrupt:
        print("\n[run] interrupted — finishing current case, journal is resumable")
        run_status = "stopped"
    else:
        run_status = "aborted" if aborted else "finished"
    finally:
        _flush_traces(suite.project)
        journal.update_meta(
            status=run_status, finished_at=datetime.now(UTC).isoformat(timespec="seconds")
        )

    return _publish_run(journal, suite, cfg, opts, cases, prices, tracker, run_records)


async def _run_cases_sequentially(
    cases: list[Case],
    suite: Suite,
    cfg: EvalConfig,
    tracker: EvalCostTracker,
    journal: RunJournal,
    healthy: list[str],
    record_case: Callable[[Case, CaseRun, dict[str, float], str, str | None], None],
) -> str | None:
    """Run cases one at a time, rotating providers within each case.

    Returns an abort reason when a backend is confirmed down — the remaining
    cases are left unrun rather than journaled as scores nobody measured.
    """
    transport = suite.transport
    aborted: str | None = None
    for case in cases:
        if tracker.total_exceeded:
            # A budget stop is a deliberate halt, not a finished run: the cases
            # after the cap were never attempted, so publishing this as
            # "finished" would finalize a partial run as a complete experiment.
            print(f"[budget] total cap exceeded — stopping before {case.id}")
            aborted = "total budget cap exceeded — remaining cases were not attempted"
            break
        last_error: str | None = None
        # Rotation is per case. It used to persist across cases, so once an
        # earlier case had rotated past the last provider, every remaining
        # case skipped the loop entirely — no attempt, no error, no journal
        # record. The cases did not fail; they silently ceased to exist.
        # Providers whose budget is exhausted are still skipped below, so
        # resetting costs nothing.
        provider_index = 0
        while provider_index < len(healthy):
            provider_name = healthy[provider_index]
            provider = cfg.providers[provider_name]
            if tracker.exceeded_budget.intersection({provider_name}):
                print(f"[budget] {provider_name} budget exhausted — rotating")
                provider_index += 1
                continue
            start = time.monotonic()
            try:
                tracker.set_provider(provider_name)
                pin_settings(provider)
                with tracker.case_scope(case.id):
                    run = await transport(case, cfg, tracker, provider)
                run.provider = provider_name
                run.model = provider.model
                run.duration_s = time.monotonic() - start
                scores = _score_or_zero(case, run, suite)
                status = _status_from_scores(case, scores, run.error)
                record_case(case, run, scores, status, run.error)
                print(
                    f"  {_MARKERS.get(status, '✗')} {case.id} [{provider_name}] "
                    + " ".join(f"{k}={v:.2f}" for k, v in scores.items())
                )
                break
            except ProviderError as e:
                last_error = str(e)
                print(f"  ✗ {case.id} [{provider_name}] provider error: {e.reason} — rotating")
                provider_index += 1
            except Exception as e:
                # An outage reaches this loop as an ordinary exception unless
                # some suite happened to hand-wrap it. Classifying here — the
                # one place a fault becomes a status — is what stops the next
                # 400 cases from measuring the outage instead of the agent,
                # whichever suite and whichever backend went away.
                fault = faults.classify(e)
                if fault is not None and faults.confirmed_down(fault):
                    aborted = str(fault.as_infra_error())
                    break
                last_error = f"{type(e).__name__}: {e}"
                record_case(
                    case,
                    _failed_run(
                        case,
                        provider_name,
                        provider.model,
                        time.monotonic() - start,
                        last_error,
                    ),
                    {},
                    "errored",
                    last_error,
                )
                print(f"  ! {case.id} [{provider_name}] errored: {last_error}")
                break
        if aborted:
            break
        # Every case leaves a record. Without the `or` clause a case that
        # never entered the loop at all — every provider over budget —
        # produced no error and so no record, and vanished from the run
        # without ever being counted as unrun.
        if journal.record_for(case.id) is None:
            reason = last_error or (
                f"no provider available: every lane in {healthy} was over budget "
                f"or exhausted before this case was attempted"
            )
            record_case(
                case,
                _failed_run(
                    case,
                    healthy[provider_index - 1] if provider_index else "?",
                    "?",
                    0,
                    reason,
                ),
                {},
                "errored",
                reason,
            )
    if aborted:
        print(f"\n[abort] {aborted}")
        if not tracker.total_exceeded:
            print(
                f"[abort] {len(cases) - len(journal.records())} case(s) did not run. "
                "Fix the backend and resume — no scores were recorded for them."
            )
    return aborted


def _app_version() -> str:
    """The app build under test: nearest tag plus short sha, or the sha alone."""

    # parents[4] resolves to apps/ — a git invocation there still finds the
    # repository root by walking up, which is all the describe needs.
    apps_dir = Path(__file__).resolve().parents[4]
    try:
        described = subprocess.run(
            ["git", "describe", "--tags", "--always", "--dirty"],
            cwd=apps_dir,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return described.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _require_meta(journal: RunJournal) -> RunMeta:
    """The run's metadata, which every path into the loop guarantees exists.

    ``run.json`` is written before the first case and only ever updated after,
    so its absence means the run directory itself is broken. Saying that is the
    whole job — the alternative, a default ``RunMeta``, publishes a run under an
    empty suite name and an empty app version as though both were real.
    """
    meta = journal.load_meta()
    if meta is None:
        raise SystemExit(f"{journal.dir} holds no run.json — the run directory is incomplete")
    return meta


def _publish_run(
    journal: RunJournal,
    suite: Suite,
    cfg: EvalConfig,
    opts: RunOptions,
    cases: list[Case],
    prices: PriceBook,
    tracker: EvalCostTracker,
    run_records: list[dict[str, Any]],
) -> Path:
    """Validate the run's numbers against themselves, then finalize and report."""
    meta = _require_meta(journal)

    # A loud stop beats a plausible figure: both defects this catches
    # (cumulative tokens, an outage scored as zeros) reached a PR because no
    # quantity was ever checked against a second, independently-derived one.
    # The check runs before finalization so a run whose numbers do not
    # reconcile is never published as an experiment at all.
    invariants = check_records(
        run_records,
        metered_by_case={
            cid: tracker.case_totals(cid)
            for cid in set(tracker.case_input) | set(tracker.case_output)
        },
        sim=opts.sim,
    )
    if not invariants.ok:
        print(invariants.render())
        raise SystemExit(2)

    if meta.status == "finished" and not opts.no_finalize:
        try:
            _finalize_experiment(suite, cfg, journal, opts, cases)
        except Exception as e:
            print(f"[finalize] failed (run still complete in journal): {e}")

    comparison = baseline.for_run(journal, rebaseline=opts.rebaseline)
    print(comparison.render())

    html_path = write_report(journal, suite.label, prices)
    _print_summary(journal, meta.suite, prices)
    print(f"[report] {html_path}")
    if not comparison.ok:
        # A regression is a result, not a crash: the report is written and the
        # journal is intact, but the exit code says the suite got worse.
        raise SystemExit(1)
    return journal.dir


async def _run_cases_concurrently(
    cases: list[Case],
    suite: Suite,
    cfg: EvalConfig,
    opts: RunOptions,
    tracker: EvalCostTracker,
    provider: ProviderConfig,
    provider_name: str,
    record_case: Callable[[Case, CaseRun, dict[str, float], str, str | None], None],
) -> str | None:
    """Run cases against one pinned provider, at most ``concurrency`` at a time.

    Safe only because a case now owns its user: two cases sharing an account
    would write over each other's todos and memory. Returns an abort reason when
    a backend is down — nothing about the agent was measured, so journaling those
    cases would publish an outage as a score.
    """
    semaphore = asyncio.Semaphore(opts.concurrency)
    aborted: str | None = None
    done = 0

    async def run_one(case: Case) -> None:
        nonlocal aborted, done
        async with semaphore:
            if aborted:
                return
            if tracker.total_exceeded:
                # Same contract as the sequential loop: a budget stop halts
                # the run without finishing it, so it is never finalized as
                # a complete experiment.
                aborted = "total budget cap exceeded — remaining cases were not attempted"
                return
            start = time.monotonic()
            try:
                with tracker.case_scope(case.id):
                    run = await suite.transport(case, cfg, tracker, provider)
                run.provider = provider_name
                run.model = provider.model
                run.duration_s = time.monotonic() - start
                scores = {} if run.error else suite.score(case, run)
                status = _status_from_scores(case, scores, run.error)
                record_case(case, run, scores, status, run.error)
            except Exception as e:
                fault = faults.classify(e)
                if fault is not None and faults.confirmed_down(fault):
                    aborted = str(fault.as_infra_error())
                    return
                detail = f"{type(e).__name__}: {e}"
                record_case(
                    case,
                    _failed_run(
                        case, provider_name, provider.model, time.monotonic() - start, detail
                    ),
                    {},
                    "errored",
                    detail,
                )
                status = "errored"
                scores = {}
            done += 1
            print(
                f"  {_MARKERS.get(status, '✗')} [{done}/{len(cases)}] {case.id} "
                + " ".join(f"{k}={v:.2f}" for k, v in scores.items())
            )

    await asyncio.gather(*(run_one(case) for case in cases))
    return aborted


def _score_or_zero(case: Case, run: CaseRun, suite: Suite) -> dict[str, float]:
    """Grade the case, or record the zero a declined case earned.

    A case that produced no answer gets no scores: scoring it would write a
    phantom 0.0 into the metric averages. A DECLINED case is the exception —
    the benchmark asked a question we have no way to answer, which is worth
    exactly zero and belongs in the average. The zero is written here rather
    than left to each suite's scorer so that every suite counts a skip the same
    way; GAIA's official scorer already treats an unanswered question as 0.0,
    and this agrees with it.
    """
    if case.skip_reason:
        return dict.fromkeys(case.gates, 0.0)
    return {} if run.error else suite.score(case, run)


def _status_from_scores(case: Case, scores: dict[str, float], error: str | None) -> str:
    """Grade a case, keeping "the agent was wrong" apart from "the case blew up".

    ``failed`` means the agent answered and missed the gate — a real quality
    signal. ``errored`` means no answer was produced (timeout, crash, dead
    backend), which is not a quality signal and must not be averaged into one.
    ``skipped`` means we declined to attempt the case at all — which IS a
    quality signal, scored zero and kept in the denominator, because the
    benchmark asked and we had no answer.
    """
    if case.skip_reason:
        # Checked before the error, deliberately: the transport signals a skip
        # by setting `error`, so reading the error first would file every skip
        # as an outage — which is how a suite scored 36/89 and published 40.4%
        # when the benchmark it claims to run has 165 questions.
        return "skipped"
    if error:
        return "errored"
    gates = case.gates
    if not gates:
        return "passed"
    gate_values = [scores.get(g, 0.0) for g in gates]
    return "passed" if all(v >= GATE_PASS_THRESHOLD for v in gate_values) else "failed"


def _log_trace(
    project: str,
    run_id: str,
    record: dict[str, Any],
    prices: PriceBook,
    suite: str,
    app_version: str,
) -> None:
    """Log one journaled case as an Opik trace with its feedback scores.

    Built from the journal record, so a live run and a later ``seed`` backfill
    produce the identical trace. Opik being down must not fail the eval run —
    the journal still holds the case and ``seed`` picks it up later — so the
    failure is reported and the loop continues.
    """
    try:
        opiksink.log_case_trace(
            project,
            CaseTrace.from_record(run_id, record, prices, suite=suite, app_version=app_version),
        )
    except Exception as e:
        print(f"[opik] trace for {record['case_id']} not logged: {type(e).__name__}: {e}")


def _flush_traces(project: str) -> None:
    """Push the run's buffered traces and shut the client down.

    Traces are batched rather than flushed per case, so the flush is what
    actually gets them into Opik. The shutdown matters just as much: the SDK's
    sender runs on non-daemon threads, so a run that only flushes leaves the
    process alive after its last case instead of exiting.
    """
    try:
        opiksink.flush(project)
    except Exception as e:
        print(f"[opik] flush failed: {type(e).__name__}: {e} — run `evals seed` to backfill")
    finally:
        opiksink.close_clients()


#: Provider-reported usage for every LLM call the case made. The real number.
TOKENS_METERED = "metered"

#: A transport's own guess, because its endpoint reports no usage. Not a
#: measurement: it sees the prompt and the answer, never the system prompt, the
#: tool schemas or the agent's intermediate turns, so it reads low by orders of
#: magnitude and must never be summed into a cost figure unlabelled.
TOKENS_ESTIMATED = "estimated"

#: Nothing was measured and nothing was claimed.
TOKENS_NONE = "none"


def _attribute_tokens(run: CaseRun, tracker: EvalCostTracker, case_id: str) -> str:
    """Settle what this case's tokens are, and say where the figure came from.

    One definition for every suite: the provider-reported input and output of
    every LLM call made while serving the case. Suites used to each answer this
    themselves and answered it five different ways — a delta on a shared meter
    (right only when one case runs at a time), a per-provider running total
    (never right), a character estimate of the prompt (low by ~1000x). The
    meter is per case now, so the harness can answer it once, here.

    A transport's own figure survives only where the meter saw nothing at all —
    an HTTP endpoint that reports no usage — and is labelled as the estimate it
    is rather than passing for a measurement.
    """
    metered_in, metered_out = tracker.case_totals(case_id)
    if metered_in or metered_out:
        run.tokens_in, run.tokens_out = metered_in, metered_out
        return TOKENS_METERED
    return TOKENS_ESTIMATED if (run.tokens_in or run.tokens_out) else TOKENS_NONE


def _record(
    case: Case,
    run: CaseRun,
    scores: dict[str, float],
    status: str,
    error: str | None,
    token_source: str = TOKENS_NONE,
) -> dict[str, Any]:
    return {
        "case_id": case.id,
        "ticket": case.ticket,
        "prompt": case.prompt,
        "expected": case.expected,
        "tags": case.tags,
        "category": case.expected.get("category"),
        "status": status,
        # Present only on a declined case, and the only thing that tells the
        # publish gate "this produced nothing because we never asked" apart from
        # "we asked and got silence" — which look identical in the record.
        "skip_reason": case.skip_reason or None,
        "provider": run.provider,
        "model": run.model,
        "text": run.text,
        "messages": run.messages,
        "tool_calls": run.tool_calls,
        "end_state": run.end_state,
        "scores": scores,
        "tokens": {"input": run.tokens_in, "output": run.tokens_out, "source": token_source},
        "duration_s": round(run.duration_s, 2),
        "error": error,
        "ts": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def _failed_run(case: Case, provider: str, model: str, duration: float, error: str) -> CaseRun:
    return CaseRun(
        case_id=case.id, provider=provider, model=model, duration_s=duration, error=error
    )


def _finalize_experiment(
    suite: Suite, cfg: EvalConfig, journal: RunJournal, opts: RunOptions, cases: list[Case]
) -> None:
    opiksink.load_opik_env()
    if not opiksink.ENV_OPIK.exists():
        print("[finalize] .env.opik missing — skipping Opik experiment")
        return

    judge_env(cfg.judge["base_url_env"], cfg.judge["api_key_env"])
    replay = _make_replay(journal)
    scorers = suite.finalize_scorers(cfg)
    tags = opts.tags + [journal.dir.name]
    opiksink.finalize(
        project=suite.project,
        cases=cases,
        journal=journal,
        scoring_metrics=scorers,
        experiment_name=journal.dir.name,
        tags=tags,
        replay=replay,
    )


def _make_replay(journal: RunJournal) -> Callable[[dict[str, object]], dict[str, object]]:
    records = {r["case_id"]: r for r in journal.records()}

    def replay(item: dict[str, Any]) -> dict[str, Any]:
        case_id = item.get("case_id", "")
        rec = records.get(case_id, {})
        return {
            "output": rec.get("text", "") or "",
            "messages": rec.get("messages", []),
            "tool_calls": rec.get("tool_calls", []),
            "end_state": rec.get("end_state"),
            "provider": rec.get("provider", ""),
            "model": rec.get("model", ""),
        }

    return replay


def _print_summary(journal: RunJournal, suite: str, prices: PriceBook) -> None:
    records = list(journal.latest_per_case().values())
    passed = sum(1 for r in records if r.get("status") == "passed")
    errored = sum(1 for r in records if r.get("status") == "errored")
    skipped = sum(1 for r in records if r.get("status") == "skipped")
    graded = len(records) - errored
    attempted = graded - skipped
    tokens_in, tokens_out = journal.tokens()
    print("\n" + "=" * 60)
    # Two numbers, and which is which has to be unmistakable. The headline is
    # over everything the benchmark asked, counting what we declined as the
    # zeros they are — that is the figure comparable to anyone else's. The
    # second is diagnostic: how the agent does on what it can attempt at all.
    # Errors are excluded from both, because an outage measured nothing.
    if graded:
        print(
            f"SUITE {suite} · "
            f"FULL SPLIT {passed}/{graded} = {passed / graded * 100:.1f}% "
            f"(skips count as zero — comparable to the benchmark)"
        )
        if attempted:
            print(
                f"  attempted-only {passed}/{attempted} = {passed / attempted * 100:.1f}% "
                f"(diagnostic only — NOT comparable, {skipped} case(s) removed)"
            )
        print(f"  cases {len(records)} · graded {graded} · skipped {skipped} · errored {errored}")
    else:
        print(f"no cases graded · {skipped} skipped · {errored} errored")
    print(f"tokens: {tokens_in:,} in / {tokens_out:,} out · est USD {journal.cost_usd(prices):.2f}")
    per_provider: dict[str, tuple[int, int]] = {}
    for r in records:
        bucket = per_provider.setdefault(r.get("provider", "?"), (0, 0))
        per_provider[r.get("provider", "?")] = (
            bucket[0] + int(r.get("tokens", {}).get("input", 0)),
            bucket[1] + int(r.get("tokens", {}).get("output", 0)),
        )
    for p, (i, o) in sorted(per_provider.items()):
        print(f"  provider {p}: {i:,} in / {o:,} out")
    print("=" * 60)
