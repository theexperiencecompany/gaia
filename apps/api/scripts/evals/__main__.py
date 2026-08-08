"""Eval harness CLI — python -m scripts.evals <run|report|cost|seed|dashboards> [options]."""

from __future__ import annotations

import argparse
import asyncio
from contextlib import suppress
from importlib import import_module
import sys

sys.stdout.reconfigure(line_buffering=True)


def _load_suites() -> None:
    """Import every suite module so @register_suite fires (missing ones are
    simply not available — e.g. when a suite's optional deps are absent)."""
    from .core.opiksink import load_opik_env

    load_opik_env()
    for _suite_module in (
        "smoke",
        "memory",
        "capability",
        "gaia_bench",
        "quality",
        "comms",
        "safety",
        "hil",
        "longmemeval",
        "regression",
    ):
        with suppress(ImportError):
            import_module(f".suites.{_suite_module}", __package__)


def main() -> None:
    _load_suites()
    parser = argparse.ArgumentParser(prog="evals", description="GAIA eval harness")
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="run a suite")
    run_p.add_argument(
        "--suite",
        required=True,
        help="suite name (memory, gaia, capability, quality, smoke, regression)",
    )
    run_p.add_argument("--resume", help="resume an existing run id")
    run_p.add_argument("--limit", type=int, help="run at most N cases")
    run_p.add_argument("--from", dest="from_case", help="start at case id")
    run_p.add_argument("--only", help="comma list of exact case ids to run")
    run_p.add_argument("--only-failed", action="store_true", help="only re-run failed cases")
    run_p.add_argument("--providers", help="comma list, e.g. nous,opencode")
    run_p.add_argument("--exclude", help="comma list of providers to exclude")
    run_p.add_argument("--max-usd", type=float, help="hard run cost cap")
    run_p.add_argument(
        "--sim", action="store_true", help="use the scripted LLM stub (free, deterministic)"
    )
    run_p.add_argument(
        "--no-finalize", action="store_true", help="skip the Opik experiment finalize"
    )
    run_p.add_argument("--tag", action="append", default=[], help="experiment tag (repeatable)")
    run_p.add_argument(
        "--rebaseline",
        action="store_true",
        help="record this run as the suite's baseline (deliberate; never automatic)",
    )
    run_p.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="run N cases at once (pins one provider; rotation is sequential-only)",
    )

    report_p = sub.add_parser("report", help="regenerate HTML report for a run")
    report_p.add_argument("run_id")

    cost_p = sub.add_parser("cost", help="project eval cost from journal history")
    cost_p.add_argument("--project", action="store_true")

    seed_p = sub.add_parser("seed", help="backfill Opik from every run journal (idempotent)")
    seed_p.add_argument(
        "--reset",
        action="store_true",
        help="delete existing case traces first (use when the trace shape changed)",
    )
    seed_p.add_argument(
        "--prune",
        action="store_true",
        help="also collapse duplicate traces (slow: a delete costs ~3.5s on this backend)",
    )

    sub.add_parser("flaky", help="cases whose verdict changes between runs (free, from journals)")

    sub.add_parser("dashboards", help="create/refresh the Opik dashboards (idempotent)")

    verify_p = sub.add_parser(
        "verify", help="prove every case's gates can reject a worthless run (no model, no DB)"
    )
    verify_p.add_argument("--suite", help="only this suite (default: every registered suite)")

    from .core import runner
    from .core.providers import load_config, price_book

    args = parser.parse_args()

    if args.command == "run" and args.sim:
        import os

        os.environ["GAIA_SIM_MODE"] = "1"
        os.environ.setdefault(
            "OPENROUTER_BASE_URL",
            f"http://localhost:{os.environ.get('LLM_STUB_PORT', '9797')}/api/v1",
        )

    cfg = load_config()

    if args.command == "run":
        opts = runner.RunOptions(
            suite=args.suite,
            resume=args.resume,
            limit=args.limit,
            from_case=args.from_case,
            only=args.only.split(",") if args.only else None,
            only_failed=args.only_failed,
            providers=args.providers.split(",") if args.providers else None,
            exclude=args.exclude.split(",") if args.exclude else None,
            max_usd=args.max_usd,
            sim=args.sim,
            no_finalize=args.no_finalize,
            tags=args.tag,
            concurrency=args.concurrency,
            rebaseline=args.rebaseline,
        )
        asyncio.run(runner.run_suite(cfg, opts))
    elif args.command == "report":
        from .core.report import write_report

        journal = runner.RunJournal(runner.RUNS_DIR, args.run_id)
        prices = price_book(cfg)
        label = (journal.load_meta() or runner.RunMeta(args.run_id, "?", "?")).suite
        path = write_report(journal, label, prices)
        print(path)
    elif args.command == "cost":
        from .core.project import project

        project(runner.RUNS_DIR, price_book(cfg))
    elif args.command == "seed":
        from .core.seed import seed

        seed(cfg, reset=args.reset, prune=args.prune)
    elif args.command == "dashboards":
        from .core.dashboards import build

        build()
    elif args.command == "flaky":
        from .core.flaky import report

        print(report(runner.RUNS_DIR))
    elif args.command == "verify":
        sys.exit(_verify(cfg, args.suite))


def _verify(cfg: object, only: str | None) -> int:
    """Falsifiability sweep across every registered suite.

    Exits non-zero when any case's gate accepted a worthless run, so this can
    gate a report or a merge without anyone remembering to look.
    """
    from .core.counterfeit import check_suite, format_report, summary_counts
    from .core.runner import SUITE_REGISTRY

    names = [only] if only else sorted(SUITE_REGISTRY)
    verdicts = []
    for name in names:
        factory = SUITE_REGISTRY.get(name)
        if factory is None:
            print(f"[verify] unknown suite {name!r}")
            return 2
        suite = factory(cfg)
        try:
            cases = suite.load_cases(cfg)
        except Exception as e:
            print(f"[verify] {name}: could not load cases: {type(e).__name__}: {e}")
            continue
        verdicts.extend(check_suite(suite, cases))
        print(f"[verify] {name:<14} {len(cases):>4} cases")

    print(format_report(verdicts))
    counts = summary_counts(verdicts)
    return 1 if counts["broken"] or counts["errored"] else 0


if __name__ == "__main__":
    sys.exit(main())
