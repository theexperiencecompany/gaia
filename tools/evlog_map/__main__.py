"""CLI for the FastAPI evlog map.

Usage:
    python3 tools/evlog_map [paths ...]           # full scan (apps/api/app + apps/voice-agent/src)
    python3 tools/evlog_map --all                 # per-entry check matrix
    python3 tools/evlog_map --min-score 70        # exit 1 below the threshold
    python3 tools/evlog_map --min-entries 300     # exit 1 when discovery finds fewer
    python3 tools/evlog_map --files-from -        # scan only listed files (CI diff mode)
    python3 tools/evlog_map --json                # full map as JSON on stdout
    python3 tools/evlog_map --github-summary      # append report to $GITHUB_STEP_SUMMARY

Writes ``evlog.map.json`` (gitignored) to the repo root unless ``--no-write``.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from compare import (
    baseline_file_entries,
    compare_to_baseline,
    head_file_entries,
    load_rename_map,
)
from report import render_github_summary, render_terminal, to_json, write_map_json
from routers import collect_router_mounts
from scan import collect_worker_registry, scan, scored_entries
from schema import canonical_fields
from voice import collect_voice_registry

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCAN_PATHS = (REPO_ROOT / "apps/api/app", REPO_ROOT / "apps/voice-agent/src")
API_PACKAGE_ROOT = REPO_ROOT / "apps/api"
APP_FACTORY_MODULE = REPO_ROOT / "apps/api/app/core/app_factory.py"
WORKER_REGISTRY_MODULE = REPO_ROOT / "apps/api/app/worker.py"
VOICE_AGENT_MODULE = REPO_ROOT / "apps/voice-agent/src/agent.py"
VOICE_LLM_MODULE = REPO_ROOT / "apps/voice-agent/src/llm.py"
MAP_JSON = REPO_ROOT / "evlog.map.json"
DEFAULT_MIN_NEW_SCORE = 70


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="evlog map",
        description="Observability score for the FastAPI backend and the LiveKit voice worker.",
    )
    parser.add_argument("paths", nargs="*", help="files or directories to scan")
    parser.add_argument(
        "--files-from",
        metavar="FILE",
        help="newline-separated file list to scan ('-' for stdin); non-.py lines are ignored",
    )
    parser.add_argument(
        "--min-score", type=int, metavar="N", help="exit 1 when the score falls below N"
    )
    parser.add_argument(
        "--min-entries",
        type=int,
        metavar="N",
        help=(
            "exit 1 when discovery finds fewer than N scored entry points — a broken "
            "scanner sees nothing and reports a perfect 100"
        ),
    )
    parser.add_argument(
        "--baseline",
        metavar="MAP_JSON",
        help=(
            "a previous --json output to ratchet against, per file: exit 1 when any "
            "file scores below its baseline, or a file absent from the baseline "
            "scores below --min-new-score"
        ),
    )
    parser.add_argument(
        "--rename-map",
        metavar="FILE",
        help="tab-separated old<TAB>new pairs mapping baseline paths to HEAD paths",
    )
    parser.add_argument(
        "--min-new-score",
        type=int,
        default=DEFAULT_MIN_NEW_SCORE,
        metavar="N",
        help="per-file floor for files with no baseline entry (with --baseline)",
    )
    parser.add_argument("--all", action="store_true", help="show the per-entry check matrix")
    parser.add_argument("--json", action="store_true", help="print the full map as JSON")
    parser.add_argument(
        "--github-summary",
        action="store_true",
        help="append a markdown report to $GITHUB_STEP_SUMMARY",
    )
    parser.add_argument(
        "--no-write", action="store_true", help="skip writing evlog.map.json to the repo root"
    )
    return parser.parse_args(argv)


def _resolve_input_path(raw: str) -> Path:
    """Resolve a CLI-supplied file path, rejecting traversal out of the CWD.

    Relative paths are confined to the working directory; absolute paths are
    accepted as-is. This keeps the tool from reading arbitrary files when it
    is driven by an agent with faulty arguments (CWE-22).
    """
    path = Path(raw)
    resolved = path.resolve()
    if not path.is_absolute():
        base = Path.cwd().resolve()
        if resolved != base and not resolved.is_relative_to(base):
            raise SystemExit(f"evlog map: refusing path outside the working directory: {raw}")
    return resolved


def _resolve_paths(args: argparse.Namespace) -> list[Path]:
    paths = [Path(p) for p in args.paths]
    if args.files_from:
        raw = (
            sys.stdin.read()
            if args.files_from == "-"
            else _resolve_input_path(args.files_from).read_text(encoding="utf-8")
        )
        paths += [Path(line.strip()) for line in raw.splitlines() if line.strip().endswith(".py")]
    if not paths and not args.files_from:
        paths = list(DEFAULT_SCAN_PATHS)
    missing = [p for p in paths if not p.exists()]
    if missing:
        raise SystemExit(
            "evlog map: input path(s) do not exist: " + ", ".join(str(p) for p in missing)
        )
    return paths


def main(argv: list[str]) -> int:
    """Scan, render, and apply the ``--min-score`` / ``--baseline`` gates."""
    args = _parse_args(argv)
    paths = _resolve_paths(args)
    fields = canonical_fields(REPO_ROOT)
    worker_registry = collect_worker_registry(WORKER_REGISTRY_MODULE)
    voice_registry = collect_voice_registry(VOICE_AGENT_MODULE, VOICE_LLM_MODULE)
    router_mounts = collect_router_mounts(APP_FACTORY_MODULE, API_PACKAGE_ROOT)
    result = scan(paths, fields, worker_registry, voice_registry, router_mounts)

    if not args.no_write:
        write_map_json(result, MAP_JSON)

    if args.json:
        print(json.dumps(to_json(result), indent=2))
    else:
        print(render_terminal(result, show_all=args.all))

    if args.github_summary:
        summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary_path:
            with Path(summary_path).open("a", encoding="utf-8") as fh:
                fh.write(render_github_summary(result) + "\n")

    failed = False
    if args.min_score is not None and result.score < args.min_score:
        print(
            f"\nscore {result.score} is below --min-score {args.min_score}",
            file=sys.stderr,
        )
        failed = True
    if args.min_entries is not None:
        # The score says nothing about what was never discovered: a framework
        # upgrade or refactor that hides entry points reads as a perfect run.
        # Assert the surface is still there before trusting the number.
        entry_count = len(scored_entries(result.entries))
        if entry_count < args.min_entries:
            print(
                f"\ndiscovery found {entry_count} scored entry point(s), below "
                f"--min-entries {args.min_entries} — the scan is not seeing the surface",
                file=sys.stderr,
            )
            failed = True
    if args.baseline:
        baseline = json.loads(_resolve_input_path(args.baseline).read_text(encoding="utf-8"))
        failures = compare_to_baseline(
            head_file_entries(result),
            baseline_file_entries(baseline),
            load_rename_map(Path(args.rename_map)) if args.rename_map else {},
            args.min_new_score,
        )
        for failure in failures:
            print(failure, file=sys.stderr)
        if failures:
            failed = True
    if result.unparsable and (args.min_score is not None or args.baseline):
        # A file that will not parse is a real failure of the gate, not a
        # cosmetic warning — otherwise breaking parse deletes its coverage
        # from the score and the ratchet waves the regression through.
        for path in result.unparsable:
            print(
                f"gate failure: {path} failed to parse — its entry points are unscored",
                file=sys.stderr,
            )
        failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
