"""Eval harness CLI — python -m scripts.evals <run|report|cost|seed|dashboards> [options]."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Callable
from importlib import import_module
import os
import sys

from pydantic import ValidationError

from .core import baseline, runner
from .core.counterfeit import check_suite, format_report, summary_counts
from .core.dashboards import build as build_dashboards
from .core.flaky import report as flaky_report
from .core.ingest import rebuild, verify as verify_ingest
from .core.ingest_check import api_base
from .core.opiksink import load_opik_env
from .core.project import project
from .core.providers import EvalConfig, load_config, price_book
from .core.report import write_report
from .core.rescore import rescore, write_sibling
from .core.runner import SUITE_REGISTRY
from .core.seed import seed
from .core.sweep import plan, render

sys.stdout.reconfigure(line_buffering=True)


def _load_suites() -> None:
    """Import every suite module so @register_suite fires; one that cannot import is an error.

    No suite has an optional dependency (all of them come with --group backend),
    so an ImportError is a broken suite, never an absent extra.
    """
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
        "ownership",
        "hil_judge",
        "hil_reply",
        "longmemeval",
        "regression",
        "browser",
    ):
        import_module(f".suites.{_suite_module}", __package__)


def _build_parser() -> argparse.ArgumentParser:
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

    ingest_p = sub.add_parser(
        "ingest", help="delete the gaia-* Opik projects and rebuild them from the journals"
    )
    ingest_p.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be deleted and written, then stop without touching Opik",
    )
    ingest_p.add_argument(
        "--pilot",
        action="store_true",
        help="ingest smoke first, then a longmemeval slice, verifying between stages",
    )
    ingest_p.add_argument(
        "--skip-teardown",
        action="store_true",
        help="rebuild in place without deleting the projects first",
    )

    sub.add_parser(
        "ingest-check", help="read every Opik project back and fail if the numbers are impossible"
    )

    rescore_p = sub.add_parser(
        "rescore", help="re-grade a finished run from its journal (no model calls)"
    )
    rescore_p.add_argument("run_id")

    compare_p = sub.add_parser(
        "compare", help="score a finished run against its suite's baseline (free, from the journal)"
    )
    compare_p.add_argument("run_id")
    compare_p.add_argument(
        "--rebaseline",
        action="store_true",
        help="record this run as the suite's baseline instead of judging against it",
    )
    compare_p.add_argument(
        "--provisional",
        default="",
        metavar="WHY",
        help="record WHY this baseline is not yet a trustworthy reference point; "
        "every later comparison against it prints the reason",
    )

    sub.add_parser("flaky", help="cases whose verdict changes between runs (free, from journals)")

    sub.add_parser(
        "sweep",
        help="find runs still holding errored cases; print the retry plan and exit "
        "non-zero while any remain (retryable ones name their resume command)",
    )

    sub.add_parser("dashboards", help="create/refresh the Opik dashboards (idempotent)")

    verify_p = sub.add_parser(
        "verify", help="prove every case's gates can reject a worthless run (no model, no DB)"
    )
    verify_p.add_argument("--suite", help="only this suite (default: every registered suite)")
    return parser


def main() -> int | None:
    _load_suites()
    args = _build_parser().parse_args()

    if args.command == "run" and args.sim:
        os.environ["GAIA_SIM_MODE"] = "1"
        os.environ.setdefault(
            "OPENROUTER_BASE_URL",
            f"http://localhost:{os.environ.get('LLM_STUB_PORT', '9797')}/api/v1",
        )

    return _COMMANDS[args.command](load_config(), args)


def _run(cfg: EvalConfig, args: argparse.Namespace) -> int | None:
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
    return None


def _report(cfg: EvalConfig, args: argparse.Namespace) -> int | None:
    journal = runner.RunJournal(runner.RUNS_DIR, args.run_id)
    label = (journal.load_meta() or runner.RunMeta(args.run_id, "?", "?")).suite
    print(write_report(journal, label, price_book(cfg)))
    return None


def _cost(cfg: EvalConfig, _args: argparse.Namespace) -> int | None:
    project(runner.RUNS_DIR, price_book(cfg))
    return None


def _seed(cfg: EvalConfig, args: argparse.Namespace) -> int | None:
    seed(cfg, reset=args.reset)
    return None


def _ingest(cfg: EvalConfig, args: argparse.Namespace) -> int | None:
    return rebuild(cfg, dry_run=args.dry_run, pilot=args.pilot, skip_teardown=args.skip_teardown)


def _ingest_check(_cfg: EvalConfig, _args: argparse.Namespace) -> int | None:
    ok, report = verify_ingest(api_base(os.environ["OPIK_URL_OVERRIDE"]))
    print(report)
    return 0 if ok else 1


def _dashboards(_cfg: EvalConfig, _args: argparse.Namespace) -> int | None:
    build_dashboards()
    return None


def _rescore(cfg: EvalConfig, args: argparse.Namespace) -> int | None:
    result = rescore(runner.RUNS_DIR, args.run_id, cfg)
    print(result.render())
    print(f"[rescore] {write_sibling(runner.RUNS_DIR, result)}")
    return None


def _compare(_cfg: EvalConfig, args: argparse.Namespace) -> int | None:
    comparison = baseline.for_run(
        runner.RunJournal(runner.RUNS_DIR, args.run_id),
        rebaseline=args.rebaseline,
        provisional=args.provisional,
    )
    print(comparison.render())
    # A regression is a result, not a crash: the verdict is printed first, then the
    # exit code carries it to whatever called this.
    sys.exit(0 if comparison.ok else 1)


def _flaky(_cfg: EvalConfig, _args: argparse.Namespace) -> int | None:
    print(flaky_report(runner.RUNS_DIR))
    return None


def _sweep(_cfg: EvalConfig, _args: argparse.Namespace) -> int | None:
    sweeps = plan(runner.RUNS_DIR)
    print(render(sweeps))
    sys.exit(1 if sweeps else 0)


def _verify_command(cfg: EvalConfig, args: argparse.Namespace) -> int | None:
    sys.exit(_verify(cfg, args.suite))


_COMMANDS: dict[str, Callable[[EvalConfig, argparse.Namespace], int | None]] = {
    "run": _run,
    "report": _report,
    "cost": _cost,
    "seed": _seed,
    "ingest": _ingest,
    "ingest-check": _ingest_check,
    "dashboards": _dashboards,
    "rescore": _rescore,
    "compare": _compare,
    "flaky": _flaky,
    "sweep": _sweep,
    "verify": _verify_command,
}


def _verify(cfg: object, only: str | None) -> int:
    """Falsifiability sweep across every registered suite.

    Exits non-zero when any case's gate accepted a worthless run, so this can
    gate a report or a merge without anyone remembering to look.
    """
    names = [only] if only else sorted(SUITE_REGISTRY)
    verdicts = []
    unloadable: list[str] = []
    for name in names:
        factory = SUITE_REGISTRY.get(name)
        if factory is None:
            print(f"[verify] unknown suite {name!r}")
            return 2
        suite = factory(cfg)
        try:
            cases = suite.load_cases(cfg)
        except Exception as e:
            unloadable.append(name)
            print(f"[verify] {name}: DID NOT LOAD — {_load_failure(e)}")
            continue
        verdicts.extend(check_suite(suite, cases))
        print(f"[verify] {name:<14} {len(cases):>4} cases")

    print(format_report(verdicts))
    if unloadable:
        # A suite that never loaded contributes zero cases, which used to look
        # like zero defects and print an all-clear; it must never report green
        # on suites it did not actually check.
        print(
            f"\n!! {len(unloadable)} suite(s) NOT CHECKED: {', '.join(unloadable)}\n"
            f"!! Their cases are absent from every number above."
        )
    counts = summary_counts(verdicts)
    return 1 if unloadable or counts["broken"] or counts["errored"] or counts["inert"] else 0


def _load_failure(error: Exception) -> str:
    """Say whether the run is misconfigured or the cases are broken.

    A settings failure reported as "could not load cases" sends the reader
    hunting through YAML for an hour. Pydantic raises ValidationError for a
    bad env var, and it may arrive wrapped, so the whole cause chain is checked.
    """
    chain: list[BaseException] = []
    current: BaseException | None = error
    while current is not None and current not in chain:
        chain.append(current)
        current = current.__cause__ or current.__context__
    config_error = next((e for e in chain if isinstance(e, ValidationError)), None)
    if config_error is not None:
        fields = ", ".join(str(d.get("loc", ("?",))[0]) for d in config_error.errors())
        return (
            f"CONFIGURATION ERROR, not a case defect: {fields} failed validation. "
            f"This is your environment (Infisical injects some keys empty). "
            f"Set it and re-run, e.g. E2B_DOMAIN=e2b.dev uv run ...\n"
            f"           {config_error}"
        )
    return f"{type(error).__name__}: {error}"


if __name__ == "__main__":
    sys.exit(main())
