"""CLI entrypoint for the persona thrash harness.

    uv run python -m scripts.persona_harness --persona empty-day-zero
    uv run python -m scripts.persona_harness --persona all --report
    uv run python -m scripts.persona_harness --persona founder-week --sim

Run against a live stack booted per the ``driving-gaia`` skill (``mise dev
--agent`` for real judgment, ``mise dev --sim`` — pass ``--sim`` here too — for
deterministic plumbing runs). Exits non-zero if any persona's assertions fail.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import traceback

import httpx

from scripts.persona_harness import founder_week, steps
from scripts.persona_harness.personas import PERSONAS, PersonaFn
from scripts.persona_harness.report import AssertionFailure, Report
from scripts.persona_harness.steps import HarnessContext

_ALL_RUNNABLE: dict[str, PersonaFn] = {**PERSONAS, "founder-week": founder_week.run}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--persona",
        required=True,
        choices=[*_ALL_RUNNABLE.keys(), "all"],
        help="persona name, or 'all' to run the whole matrix (not founder-week)",
    )
    parser.add_argument("--api", default="http://localhost:8000/api/v1", help="API base URL")
    parser.add_argument(
        "--sim", action="store_true", help="the target stack is running under --sim (scripted LLM)"
    )
    parser.add_argument("--report", action="store_true", help="write a markdown report per persona")
    parser.add_argument("--keep-user", action="store_true", help="skip teardown (debugging)")
    return parser.parse_args()


async def _run_one(
    name: str, fn: PersonaFn, *, api: str, sim: bool, write_report: bool, keep_user: bool
) -> bool:
    report = Report(persona=name)
    ctx = HarnessContext(email=f"persona-{name}@gaia.local", api_base=api, sim=sim, report=report)
    ok = True
    try:
        await fn(ctx)
    except AssertionFailure as exc:
        ok = False
        print(f"\n[{name}] FAILED: {exc}", file=sys.stderr)
    except Exception:
        ok = False
        print(f"\n[{name}] ERRORED:\n{traceback.format_exc()}", file=sys.stderr)
    finally:
        if not keep_user:
            try:
                await steps.delete_user(ctx)
            except (httpx.HTTPError, AssertionError) as teardown_exc:
                # Teardown must never mask the real result — a torn-down
                # user's assertions above already decided pass/fail.
                print(f"[{name}] teardown warning: {teardown_exc}", file=sys.stderr)
        if write_report:
            path = report.write()
            print(f"[{name}] report written to {path}")
        await ctx.aclose()

    # A non-raising Report.observe() miss doesn't hit the except blocks above
    # but still belongs in the FAIL column. An assertion-free run is
    # INCONCLUSIVE, never a pass — see Report.status.
    ok = ok and report.status == "PASS"
    print(f"[{name}] {report.status} — {len(report.passed)} passed, {len(report.failed)} failed")
    return ok


async def _main_async() -> int:
    args = _parse_args()
    names = list(PERSONAS.keys()) if args.persona == "all" else [args.persona]

    results = []
    for name in names:
        fn = _ALL_RUNNABLE[name]
        ok = await _run_one(
            name,
            fn,
            api=args.api,
            sim=args.sim,
            write_report=args.report,
            keep_user=args.keep_user,
        )
        results.append((name, ok))

    print("\n=== persona thrash summary ===")
    for name, ok in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")

    return 0 if all(ok for _, ok in results) else 1


def main() -> None:
    sys.exit(asyncio.run(_main_async()))


if __name__ == "__main__":
    main()
