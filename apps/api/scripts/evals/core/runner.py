"""The run loop: journal → provider rotation → run → score → append → finalize."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
import time
from typing import Any
import uuid

from .cost import EvalCostTracker
from .journal import RunJournal, RunMeta
from .providers import (
    EvalConfig,
    ProviderConfig,
    health_check,
    pin_settings,
    price_book,
    rotation_chain,
)
from .types import Case, CaseRun, CaseTrace, InfraError, PriceBook, ProviderError

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
    journal = RunJournal(RUNS_DIR, run_id)
    if opts.resume is None:
        journal.create_meta(
            RunMeta(
                run_id=run_id,
                suite=suite.name,
                started_at=datetime.now(UTC).isoformat(timespec="seconds"),
                provider_order=order,
                tags=opts.tags,
            )
        )

    tracker = EvalCostTracker(cfg.providers, opts.max_usd or cfg.default_max_usd)
    transport = suite.transport

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

    cases = suite.load_cases(cfg)
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
    if opts.limit is not None:
        cases = cases[: opts.limit]
    if opts.resume:
        cases = [c for c in cases if not journal.has_terminal(c.id)]
    if opts.only_failed:
        cases = [c for c in cases if (journal.record_for(c.id) or {}).get("status") == "failed"]

    print(f"[run] {run_id} · suite={suite.name} · providers={healthy} · cases={len(cases)}")

    provider_index = 0
    prices = price_book(cfg)

    def record_case(
        case: Case, run: CaseRun, scores: dict[str, float], status: str, error: str | None
    ) -> None:
        """Journal a finished case and mirror it into Opik — including failures,
        which are exactly the cases worth looking at in the UI."""
        record = _record(case, run, scores, status, error)
        journal.append(record)
        _log_trace(suite.project, run_id, record, prices)

    aborted: str | None = None
    run_status = "finished"

    try:
        for case in cases:
            if tracker.total_exceeded:
                print(f"[budget] total cap exceeded — stopping before {case.id}")
                break
            attempt = 0
            last_error: str | None = None
            while provider_index < len(healthy):
                provider_name = healthy[provider_index]
                provider = cfg.providers[provider_name]
                if tracker.exceeded_budget.intersection({provider_name}):
                    print(f"[budget] {provider_name} budget exhausted — rotating")
                    provider_index += 1
                    continue
                attempt += 1
                start = time.monotonic()
                try:
                    tracker.set_provider(provider_name)
                    pin_settings(provider)
                    run = await transport(case, cfg, tracker, provider)
                    run.provider = provider_name
                    run.model = provider.model
                    run.duration_s = time.monotonic() - start
                    # A case that produced no answer gets no scores: scoring it
                    # would write a phantom 0.0 into the metric averages.
                    scores = {} if run.error else suite.score(case, run)
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
                except InfraError as e:
                    # Nothing about the agent was measured — journaling this case
                    # (and every one after it) would publish an outage as a 0%.
                    aborted = str(e)
                    break
                except Exception as e:
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
            if last_error and journal.record_for(case.id) is None:
                record_case(
                    case,
                    _failed_run(
                        case,
                        healthy[provider_index - 1] if provider_index else "?",
                        "?",
                        0,
                        last_error,
                    ),
                    {},
                    "errored",
                    last_error,
                )
        if aborted:
            print(
                f"\n[abort] {aborted}\n"
                f"[abort] {len(cases) - len(journal.records())} case(s) did not run. "
                "Fix the backend and resume — no scores were recorded for them."
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

    if journal.load_meta().status == "finished" and not opts.no_finalize:
        try:
            _finalize_experiment(suite, cfg, journal, opts, cases)
        except Exception as e:
            print(f"[finalize] failed (run still complete in journal): {e}")

    from .report import write_report

    html_path = write_report(journal, suite.label, prices)
    _print_summary(journal, prices)
    print(f"[report] {html_path}")
    return journal.dir


def _status_from_scores(case: Case, scores: dict[str, float], error: str | None) -> str:
    """Grade a case, keeping "the agent was wrong" apart from "the case blew up".

    ``failed`` means the agent answered and missed the gate — a real quality
    signal. ``errored`` means no answer was produced (timeout, crash, dead
    backend), which is not a quality signal and must not be averaged into one.
    """
    if error:
        return "errored"
    gates = case.gates
    if not gates:
        return "passed"
    gate_values = [scores.get(g, 0.0) for g in gates]
    return "passed" if all(v >= 0.5 for v in gate_values) else "failed"


def _log_trace(project: str, run_id: str, record: dict[str, Any], prices: PriceBook) -> None:
    """Log one journaled case as an Opik trace with its feedback scores.

    Built from the journal record, so a live run and a later ``seed`` backfill
    produce the identical trace. Opik being down must not fail the eval run —
    the journal still holds the case and ``seed`` picks it up later — so the
    failure is reported and the loop continues.
    """
    from .opiksink import log_case_trace

    try:
        log_case_trace(project, CaseTrace.from_record(run_id, record, prices))
    except Exception as e:
        print(f"[opik] trace for {record['case_id']} not logged: {type(e).__name__}: {e}")


def _flush_traces(project: str) -> None:
    """Push the run's buffered traces and shut the client down.

    Traces are batched rather than flushed per case, so the flush is what
    actually gets them into Opik. The shutdown matters just as much: the SDK's
    sender runs on non-daemon threads, so a run that only flushes leaves the
    process alive after its last case instead of exiting.
    """
    from .opiksink import close_clients, flush

    try:
        flush(project)
    except Exception as e:
        print(f"[opik] flush failed: {type(e).__name__}: {e} — run `evals seed` to backfill")
    finally:
        close_clients()


def _record(
    case: Case, run: CaseRun, scores: dict[str, float], status: str, error: str | None
) -> dict[str, Any]:
    return {
        "case_id": case.id,
        "ticket": case.ticket,
        "prompt": case.prompt,
        "expected": case.expected,
        "tags": case.tags,
        "category": case.expected.get("category"),
        "status": status,
        "provider": run.provider,
        "model": run.model,
        "text": run.text,
        "messages": run.messages,
        "tool_calls": run.tool_calls,
        "end_state": run.end_state,
        "scores": scores,
        "tokens": {"input": run.tokens_in, "output": run.tokens_out},
        "duration_s": round(run.duration_s, 2),
        "error": error,
        "ts": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def _failed_run(case: Case, provider: str, model: str, duration: float, error: str) -> CaseRun:
    from .types import CaseRun

    return CaseRun(
        case_id=case.id, provider=provider, model=model, duration_s=duration, error=error
    )


def _finalize_experiment(
    suite: Suite, cfg: EvalConfig, journal: RunJournal, opts: RunOptions, cases: list[Case]
) -> None:
    from . import opiksink
    from .scorers import judge_env

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


def _print_summary(journal: RunJournal, prices: PriceBook) -> None:
    records = journal.records()
    passed = sum(1 for r in records if r.get("status") == "passed")
    errored = sum(1 for r in records if r.get("status") == "errored")
    graded = len(records) - errored
    tokens_in, tokens_out = journal.tokens()
    print("\n" + "=" * 60)
    # Accuracy is over cases that actually produced an answer; errors are their
    # own number so a broken backend can never masquerade as a low score.
    print(
        f"SUITE {journal.load_meta().suite} · {passed}/{graded} passed "
        f"({passed / graded * 100:.1f}%) · {errored} errored"
        if graded
        else f"no cases graded · {errored} errored"
    )
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
