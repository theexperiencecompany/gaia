"""The run loop: journal → provider rotation → run → score → append → finalize."""

from __future__ import annotations

import asyncio
import json
import signal
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from .cost import EvalCostTracker
from .journal import RunJournal, RunMeta
from .providers import EvalConfig, ProviderConfig, health_check, pin_settings, rotation_chain
from .types import Case, ProviderError

RUNS_DIR = Path(__file__).resolve().parent.parent / "runs"

SUITE_REGISTRY: dict[str, Callable[[EvalConfig], "Suite"]] = {}


def register_suite(name: str) -> Callable[[Callable[[EvalConfig], "Suite"]], Callable[[EvalConfig], "Suite"]]:
    def decorator(factory: Callable[[EvalConfig], "Suite"]) -> Callable[[EvalConfig], "Suite"]:
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

    def score(self, case: Case, run: Any) -> dict[str, float]:
        raise NotImplementedError

    def transport(self, case: Case, cfg: EvalConfig, tracker: EvalCostTracker) -> Any:
        raise NotImplementedError

    def finalize_scorers(self, cfg: EvalConfig) -> list[Any]:
        return []


class RunOptions:
    def __init__(
        self,
        suite: str,
        resume: str | None = None,
        limit: int | None = None,
        from_case: str | None = None,
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
        raise SystemExit(f"unknown suite '{opts.suite}'. Available: {', '.join(sorted(SUITE_REGISTRY))}")
    suite = factory(cfg)

    order = rotation_chain(cfg, opts.providers, opts.exclude)
    if not order:
        raise SystemExit("no providers available (all excluded or unknown)")

    run_id = opts.resume or f"{opts.suite}-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
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
    prices = {p: (c.price_in_per_1m, c.price_out_per_1m) for p, c in cfg.providers.items()}

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
                    scores = suite.score(case, run)
                    if run.error:
                        journal.append(_record(case, run, scores, "failed", run.error))
                    else:
                        journal.append(_record(case, run, scores, "passed", None))
                    print(
                        f"  ✓ {case.id} [{provider_name}] "
                        + " ".join(f"{k}={v:.2f}" for k, v in scores.items())
                    )
                    break
                except ProviderError as e:
                    last_error = str(e)
                    print(f"  ✗ {case.id} [{provider_name}] provider error: {e.reason} — rotating")
                    provider_index += 1
                except Exception as e:  # noqa: BLE001 — suite errors are recorded, not fatal
                    last_error = f"{type(e).__name__}: {e}"
                    journal.append(
                        _record(
                            case,
                            _failed_run(case, provider_name, provider.model, time.monotonic() - start, last_error),
                            {},
                            "failed",
                            last_error,
                        )
                    )
                    break
            if last_error and journal.record_for(case.id) is None:
                journal.append(
                    _record(
                        case,
                        _failed_run(case, healthy[provider_index - 1] if provider_index else "?", "?", 0, last_error),
                        {},
                        "failed",
                        last_error,
                    )
                )
    except KeyboardInterrupt:
        print("\n[run] interrupted — finishing current case, journal is resumable")
        journal.update_meta(status="stopped")
    finally:
        journal.update_meta(status="finished", finished_at=datetime.now(UTC).isoformat(timespec="seconds"))

    if journal.load_meta().status == "finished" and not opts.no_finalize:
        try:
            _finalize_experiment(suite, cfg, journal, opts, cases, prices)
        except Exception as e:  # noqa: BLE001
            print(f"[finalize] failed (run still complete in journal): {e}")

    from .report import write_report

    html_path = write_report(journal, suite.label, prices)
    _print_summary(journal, prices)
    print(f"[report] {html_path}")
    return journal.dir


def _record(case: Case, run: Any, scores: dict[str, float], status: str, error: str | None) -> dict[str, Any]:
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
        "messages": run.messages,
        "tool_calls": run.tool_calls,
        "end_state": run.end_state,
        "scores": scores,
        "tokens": {"input": run.tokens_in, "output": run.tokens_out},
        "duration_s": round(run.duration_s, 2),
        "error": error,
        "ts": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def _failed_run(case: Case, provider: str, model: str, duration: float, error: str) -> Any:
    from .types import CaseRun

    return CaseRun(
        case_id=case.id, provider=provider, model=model, duration_s=duration, error=error
    )


def _finalize_experiment(suite: Suite, cfg: EvalConfig, journal: RunJournal, opts: RunOptions, cases: list[Case], prices: dict[str, tuple[float, float]]) -> None:
    from . import opiksink
    from .scorers import judge_env

    opiksink.load_opik_env()
    if not opiksink.ENV_OPIK.exists():
        print("[finalize] .env.opik missing — skipping Opik experiment")
        return

    judge_env(cfg.judge["base_url_env"], cfg.judge["api_key_env"])
    replay = _make_replay(journal, cases)
    scorers = suite.finalize_scorers(cfg)
    tags = opts.tags + [journal.dir.name]
    opiksink.finalize(
        project=suite.project,
        cases=cases,
        journal=journal,
        scoring_metrics=scorers,
        experiment_name=f"{suite.name}-{journal.dir.name}",
        tags=tags,
        replay=replay,
    )


def _make_replay(journal: RunJournal, cases: list[Case]) -> Callable[[dict[str, Any]], dict[str, Any]]:
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


def _print_summary(journal: RunJournal, prices: dict[str, tuple[float, float]]) -> None:
    records = journal.records()
    passed = sum(1 for r in records if r.get("status") == "passed")
    total = len(records)
    tokens_in, tokens_out = journal.tokens()
    print("\n" + "=" * 60)
    print(f"SUITE {journal.load_meta().suite} · {passed}/{total} passed ({passed / total * 100:.1f}%)" if total else "no cases ran")
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
