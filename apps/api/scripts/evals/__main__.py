"""Eval harness CLI — python -m scripts.evals <run|report|cost> [options]."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)

from .core.opiksink import load_opik_env

load_opik_env()

from .core import runner  # noqa: E402
from .core.providers import load_config  # noqa: E402

from importlib import import_module  # noqa: E402

for _suite_module in ("smoke", "memory", "capability", "gaia_bench", "quality"):
    try:
        import_module(f".suites.{_suite_module}", __package__)
    except ImportError:
        pass


def main() -> None:
    parser = argparse.ArgumentParser(prog="evals", description="GAIA eval harness")
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="run a suite")
    run_p.add_argument("--suite", required=True, help="suite name (memory, gaia, capability, quality, smoke, regression)")
    run_p.add_argument("--resume", help="resume an existing run id")
    run_p.add_argument("--limit", type=int, help="run at most N cases")
    run_p.add_argument("--from", dest="from_case", help="start at case id")
    run_p.add_argument("--only-failed", action="store_true", help="only re-run failed cases")
    run_p.add_argument("--providers", help="comma list, e.g. nous,opencode")
    run_p.add_argument("--exclude", help="comma list of providers to exclude")
    run_p.add_argument("--max-usd", type=float, help="hard run cost cap")
    run_p.add_argument("--sim", action="store_true", help="use the scripted LLM stub (free, deterministic)")
    run_p.add_argument("--no-finalize", action="store_true", help="skip the Opik experiment finalize")
    run_p.add_argument("--tag", action="append", default=[], help="experiment tag (repeatable)")

    report_p = sub.add_parser("report", help="regenerate HTML report for a run")
    report_p.add_argument("run_id")

    cost_p = sub.add_parser("cost", help="project eval cost from journal history")
    cost_p.add_argument("--project", action="store_true")

    args = parser.parse_args()
    cfg = load_config()

    if args.command == "run":
        opts = runner.RunOptions(
            suite=args.suite,
            resume=args.resume,
            limit=args.limit,
            from_case=args.from_case,
            only_failed=args.only_failed,
            providers=args.providers.split(",") if args.providers else None,
            exclude=args.exclude.split(",") if args.exclude else None,
            max_usd=args.max_usd,
            sim=args.sim,
            no_finalize=args.no_finalize,
            tags=args.tag,
        )
        asyncio.run(runner.run_suite(cfg, opts))
    elif args.command == "report":
        from .core.report import write_report

        journal = runner.RunJournal(runner.RUNS_DIR, args.run_id)
        prices = {p: (c.price_in_per_1m, c.price_out_per_1m) for p, c in cfg.providers.items()}
        label = (journal.load_meta() or runner.RunMeta(args.run_id, "?", "?")).suite
        path = write_report(journal, label, prices)
        print(path)
    elif args.command == "cost":
        from .core.project import project

        project(cfg, runner.RUNS_DIR)


if __name__ == "__main__":
    sys.exit(main())
