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

from scripts.persona_harness import founder_week
from scripts.persona_harness.personas import PERSONAS
from scripts.persona_harness.report import AssertionFailure, Report
from scripts.persona_harness.steps import HarnessContext

_ALL_RUNNABLE = {**PERSONAS, "founder-week": founder_week.run}


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
    name: str, fn: object, *, api: str, sim: bool, write_report: bool, keep_user: bool
) -> bool:
    report = Report(persona=name)
    ctx = HarnessContext(email=f"persona-{name}@gaia.local", api_base=api, sim=sim, report=report)
    ok = True
    try:
        await fn(ctx)  # type: ignore[operator]
    except AssertionFailure as exc:
        ok = False
        print(f"\n[{name}] FAILED: {exc}", file=sys.stderr)
    except Exception:
        ok = False
        print(f"\n[{name}] ERRORED:\n{traceback.format_exc()}", file=sys.stderr)
    finally:
        if not keep_user:
            try:
                from scripts.persona_harness import steps

                await steps.delete_user(ctx)
            except Exception as teardown_exc:  # noqa: BLE001 — teardown must never mask the real result
                print(f"[{name}] teardown warning: {teardown_exc}", file=sys.stderr)
        if write_report:
            path = report.write()
            print(f"[{name}] report written to {path}")
        await ctx.aclose()

    status = "PASS" if ok else "FAIL"
    print(f"[{name}] {status} — {len(report.passed)} passed, {len(report.failed)} failed")
    return ok


async def _main_async() -> int:
    args = _parse_args()
    if args.persona == "all":
        names = list(PERSONAS.keys())
    else:
        names = [args.persona]

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
