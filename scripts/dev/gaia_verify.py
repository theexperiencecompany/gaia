#!/usr/bin/env python3
"""mise ci:local — run GAIA's CI quality gates locally with agent-legible results.

Lane definitions live in scripts/dev/verify-lanes.json (mirror CI gates; edit
both in the same commit — intentionally-unmirrored CI jobs are listed there). Sequential execution by design: predictable logs,
bounded memory, no shared-state races between lanes.

Usage:
  mise ci:local [--json] [--all] [--only a,b] [--skip a,b] [--with-heavy]
              [--verbose] [--list] [--base REF]

Exit codes: 0 = all executed lanes passed (unchanged/skipped don't count);
            1 = at least one lane failed (code-quality signal — takes precedence);
            2 = infra/config problem (lane error/timeout, bad config, bad usage — not a code verdict).
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

# The lane table's `nx` tasks are answered by the same module CI's detect asks.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ci"))
from lib import nx_affected

SCHEMA_VERSION = 1
LANES_FILE = Path(__file__).resolve().parent / "verify-lanes.json"
LOG_ROOT = "verify-logs"


def eprint(*args: str) -> None:
    print(*args, file=sys.stderr, flush=True)


@dataclass
class Lane:
    name: str
    # The nx task that decides the lane, as in CI; a lane without one is scoped by its regex.
    nx: str | None
    scope_re: re.Pattern[str] | None
    heavy: bool
    timeout_s: int
    require_cmd: list[str]
    require_env: list[str]
    command: str


def _die(msg: str) -> None:
    eprint(msg)
    sys.exit(2)


def load_lanes(path: Path) -> list[Lane]:
    try:
        data = json.loads(path.read_text())
        rows = data["lanes"]
    except Exception as exc:
        _die(f"config error: {path}: unreadable lanes file: {exc}")
    if not isinstance(rows, list):
        _die(f"config error: {path}: top-level 'lanes' must be a list")
    lanes: list[Lane] = []
    seen: set[str] = set()
    for i, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            _die(f"config error: {path} lane #{i}: row must be an object")
        try:
            name = row["name"]
            if name in seen:
                raise ValueError(f"duplicate lane name '{name}'")
            if not re.fullmatch(r"[\w.-]+", name):
                raise ValueError(
                    f"lane name may contain only [A-Za-z0-9_.-] (log-file safety): {name!r}"
                )
            seen.add(name)
            lanes.append(
                Lane(
                    name=name,
                    nx=row.get("nx"),
                    scope_re=None if row.get("nx") else re.compile(row["scope"]),
                    heavy=bool(row["heavy"]),
                    timeout_s=int(row["timeout_s"]),
                    require_cmd=list(row.get("require_cmd", [])),
                    require_env=list(row.get("require_env", [])),
                    # A lane with an nx task runs it: the command lives in the task, as CI's step runs it.
                    command=row.get("command")
                    or f"pnpm exec nx run {row['nx']} --output-style=stream-without-prefixes",
                )
            )
        except Exception as exc:
            _die(f"config error: {path} lane #{i}: {exc}")
    for ln in lanes:
        if ln.timeout_s <= 0:
            _die(f"config error: {path}: lane '{ln.name}' timeout must be >= 1 second")
    if not lanes:
        _die(f"config error: {path}: no lanes defined")
    return lanes


def run(
    cmd: list[str], timeout_s: int, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout_s, cwd=cwd, check=False
    )


def pick_base(root: Path, explicit: str | None) -> str:
    """Resolve the base ref: --base flag > $GH_BASE > current PR's base via gh > origin/master."""
    if explicit:
        return explicit
    env_base = os.environ.get("GH_BASE")
    if env_base:
        return env_base
    try:
        proc = run(
            ["gh", "pr", "view", "--json", "baseRefName", "--jq", ".baseRefName"], 20, cwd=root
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return f"origin/{proc.stdout.strip()}"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return "origin/master"


def changed_files(root: Path, base: str, strict_base: bool = False) -> list[str]:
    def base_unusable(detail: str) -> None:
        if strict_base:
            _die(
                f"--base '{base}' is unusable ({detail}) — refusing to guess scope and report a false green"
            )

    files: list[str] = []
    cmds = [
        (["git", "diff", "--name-only", f"{base}...HEAD"], True),
        (["git", "diff", "--name-only", "HEAD"], False),
        (["git", "ls-files", "--others", "--exclude-standard"], False),
    ]
    for cmd, uses_base in cmds:
        try:
            proc = run(cmd, 30, cwd=root)
        except subprocess.TimeoutExpired:
            eprint(f"warning: {' '.join(cmd)} timed out; continuing without it")
            continue
        if proc.returncode == 0:
            files.extend(f for f in proc.stdout.splitlines() if f.strip())
        elif strict_base and uses_base:
            base_unusable(proc.stderr.strip()[:200])
        else:
            # Unknown/missing base ref is common on fresh clones; fall back to HEAD-only diffs.
            eprint(f"warning: {' '.join(cmd)} failed: {proc.stderr.strip()[:200]}")
    seen: set[str] = set()
    return [f for f in files if not (f in seen or seen.add(f))]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run GAIA CI quality lanes locally.")
    parser.add_argument(
        "--json", action="store_true", help="emit only the final JSON report on stdout"
    )
    parser.add_argument(
        "--all", action="store_true", help="run every lane regardless of changed files"
    )
    parser.add_argument("--only", default="", help="comma-separated lane names (overrides scoping)")
    parser.add_argument("--skip", default="", help="comma-separated lane names to exclude")
    parser.add_argument(
        "--with-heavy", action="store_true", help="include heavy lanes (tests, docker, network)"
    )
    parser.add_argument(
        "--verbose", action="store_true", help="list matched files per selected lane"
    )
    parser.add_argument("--list", action="store_true", help="print the lane table and exit")
    parser.add_argument(
        "--dry-run", action="store_true", help="show the execution plan without running any lane"
    )
    parser.add_argument(
        "--base",
        default=None,
        help="git ref to diff against (default: PR base, then origin/master)",
    )
    return parser.parse_args()


def _repo_root() -> Path:
    try:
        return Path(
            subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                capture_output=True,
                text=True,
                timeout=15,
                check=True,
            ).stdout.strip()
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        eprint(f"not inside a git repository ({exc})")
        sys.exit(2)


def _lane_names(raw: str, flag: str, lanes: list[Lane]) -> set[str]:
    names = {s.strip() for s in raw.split(",") if s.strip()}
    if raw and not names:
        _die(f"usage error: {flag} given but no lane names parsed")
    missing = names - {ln.name for ln in lanes}
    if missing:
        eprint(
            f"usage error: unknown lanes: {sorted(missing)}. `mise ci:local --list` shows the table."
        )
        sys.exit(2)
    return names


def _skip_reason(
    ln: Lane, matched: list[str], args: argparse.Namespace, only: set[str]
) -> str | None:
    """Say why a lane does not run, or None when it does; a lane named with --only skips no scoping."""
    if not only:
        if ln.heavy and not args.with_heavy:
            return "heavy (use --with-heavy)"
        if not matched and not args.all:
            return "unchanged"
    missing_tools = [c for c in ln.require_cmd if not shutil.which(c)]
    if missing_tools:
        return f"missing tool(s): {','.join(missing_tools)}"
    # A lane named with --only runs regardless, so its own missing-credential error shows.
    missing_env = [v for v in ln.require_env if not os.environ.get(v)]
    if missing_env and not only:
        return f"missing env: {','.join(missing_env)} (--only {ln.name} runs it)"
    return None


def select_lanes(
    lanes: list[Lane],
    files: list[str],
    reached: dict[str, list[dict[str, str]]],
    args: argparse.Namespace,
    only: set[str],
    skip: set[str],
) -> tuple[list[tuple[Lane, list[str]]], list[tuple[Lane, str]]]:
    def matching(ln: Lane) -> list[str]:
        if ln.nx:
            return [r["file"] for r in reached.get(ln.nx, []) if r.get("file")]
        assert ln.scope_re is not None
        return [f for f in files if ln.scope_re.search(f)]

    selected: list[tuple[Lane, list[str]]] = []
    skipped: list[tuple[Lane, str]] = []
    for ln in lanes:
        if only and ln.name not in only:
            continue
        if not only and ln.name in skip:
            skipped.append((ln, "skipped by --skip"))
            continue
        matched = matching(ln)
        why = _skip_reason(ln, matched, args, only)
        if why:
            skipped.append((ln, why))
        else:
            selected.append((ln, matched))
    return selected, skipped


def run_lane(
    ln: Lane, root: Path, log_file: Path, lane_env: dict[str, str]
) -> tuple[str, str | None, int | None, int]:
    """Run one lane into its log file; return its status, reason, exit code and duration in ms."""
    status = "passed"
    reason = None
    exit_code: int | None = None
    lane_t0 = time.monotonic()
    try:
        with open(log_file, "w") as logfh:
            proc = subprocess.run(  # noqa: S602 - lanes ARE shell pipelines (&& chains); config is repo-trusted
                ln.command,
                shell=True,
                check=False,
                cwd=root,
                env=lane_env,
                stdout=logfh,
                stderr=subprocess.STDOUT,
                timeout=ln.timeout_s,
            )
        exit_code = proc.returncode
        if proc.returncode != 0:
            status = "failed"
    except subprocess.TimeoutExpired:
        status = "timeout"
        reason = f"exceeded {ln.timeout_s}s"
    except Exception as exc:
        status = "error"
        reason = str(exc)[:300]
    return status, reason, exit_code, int((time.monotonic() - lane_t0) * 1000)


def print_summary(
    results: list[dict[str, object]], counts: dict[str, int], total_ms: int, stamp: str
) -> None:
    worst = next((r["name"] for r in results if r["status"] == "failed"), None)
    skip_breakdown: dict[str, int] = {}
    for r in results:
        if r["status"] == "skipped":
            key = str(r.get("reason", "unknown")).split(":")[0]
            skip_breakdown[key] = skip_breakdown.get(key, 0) + 1
    skips_txt = ", ".join(f"{k} x{v}" for k, v in sorted(skip_breakdown.items())) or "-"
    print(
        f"\nci:local: {counts['passed']} passed, {counts['failed']} failed, "
        f"{counts['unchanged']} unchanged (lane not touched by this diff), {counts['skipped']} skipped [{skips_txt}]"
        + (
            f", {counts['error']} error, {counts['timeout']} timeout"
            if (counts["error"] or counts["timeout"])
            else ""
        )
        + f" — total {total_ms / 1000:.1f}s (logs: {LOG_ROOT}/{stamp}/)"
    )
    failing = [str(r["name"]) for r in results if r["status"] == "failed"]
    broken = [str(r["name"]) for r in results if r["status"] in ("error", "timeout")]
    if failing:
        print("NEXT: fix the failing lanes above, then rerun:")
        print(f"  mise ci:local --only {','.join(failing)}")
        if worst:
            print(f"  worst offender: {worst} — full log: {LOG_ROOT}/{stamp}/{worst}.log")
    if broken:
        print("NEXT: infra/config problems (not code): inspect logs, fix environment, rerun:")
        print(f"  mise ci:local --only {','.join(broken)}")
    if not failing and not broken:
        print("NEXT: all local gates green — push, then `mise ci:remote` for GitHub gate state")


def print_table(lanes: list[Lane]) -> None:
    for ln in lanes:
        reqs = "+".join(ln.require_cmd) if ln.require_cmd else "-"
        print(
            f"{ln.name:32} heavy={ln.heavy!s:5} timeout={ln.timeout_s:>5}s requires={reqs:20} {ln.command[:90]}"
        )


def print_plan(
    selected: list[tuple[Lane, list[str]]],
    total: int,
    args: argparse.Namespace,
    say: Callable[[str], None],
) -> None:
    say(f"dry-run: would execute {len(selected)} of {total} lanes:")
    for i, (ln, matched) in enumerate(selected, 1):
        extra = f", {len(matched)} matched files" if not args.all else ", --all"
        say(f"  [{i}/{len(selected)}] {ln.name} (timeout {ln.timeout_s}s{extra})")
    say("dry-run: nothing was executed.")


def execute_lanes(
    selected: list[tuple[Lane, list[str]]],
    root: Path,
    log_dir: Path,
    lane_env: dict[str, str],
    args: argparse.Namespace,
    say: Callable[[str], None],
) -> list[dict[str, object]]:
    """Run every selected lane in order and return one report entry per lane."""
    results: list[dict[str, object]] = []
    for i, (ln, matched) in enumerate(selected, 1):
        suffix = f" ({len(matched)} matched files)" if not args.all else ""
        detail = (
            f" — {', '.join(matched[:5])}{'…' if len(matched) > 5 else ''}"
            if args.verbose and matched
            else ""
        )
        say(f"[{i}/{len(selected)}] {ln.name}{suffix}{detail} … running (timeout {ln.timeout_s}s)")
        log_file = log_dir / f"{ln.name}.log"
        status, reason, exit_code, duration_ms = run_lane(ln, root, log_file, lane_env)

        icon = {"passed": "pass", "failed": "FAIL", "timeout": "TIMEOUT", "error": "ERROR"}[status]
        say(f"      -> {icon:7} {ln.name} [{duration_ms} ms]" + (f" — {reason}" if reason else ""))
        if status == "failed":
            tail = Path(log_file).read_text(errors="replace").splitlines()[-40:]
            say(
                "      ┌─ last 40 lines "
                + "─" * 30
                + "\n      │ "
                + "\n      │ ".join(tail)
                + "\n      └"
                + "─" * 48
            )

        entry: dict[str, object] = {
            "name": ln.name,
            "status": status,
            "durationMs": duration_ms,
            "logFile": str(log_file.relative_to(root)),
        }
        if exit_code is not None:
            entry["exitCode"] = exit_code
        if reason:
            entry["reason"] = reason
        if matched and not args.all:
            entry["matchedFiles"] = len(matched)
        results.append(entry)

    return results


def main() -> int:
    args = _parse_args()
    root = _repo_root()
    lanes = load_lanes(LANES_FILE)

    if args.list:
        print_table(lanes)
        return 0

    only = _lane_names(args.only, "--only", lanes)
    skip = _lane_names(args.skip, "--skip", lanes)

    base = pick_base(root, args.base)
    files = changed_files(root, base, strict_base=args.base is not None)

    started_at = datetime.now(UTC)
    t0 = time.monotonic()
    results: list[dict[str, object]] = []

    stamp = started_at.strftime("%Y%m%d-%H%M%S") + f"-{os.getpid()}"
    log_dir = root / LOG_ROOT / stamp

    def say(msg: str) -> None:
        if not args.json:
            print(msg, flush=True)

    MIN_PYTHON = (3, 11)  # tomllib / match-statements used by several lane tools
    if sys.version_info < MIN_PYTHON:
        eprint(
            f"warning: running under python {sys.version.split()[0]}; several lanes need >=3.11 "
            "(tomllib, match-statements). Run through mise so PATH resolves python 3.12: `mise ci:local …`"
        )
    say(f"ci:local: base={base} changed_files={len(files)} lanes_total={len(lanes)}")

    reached = (
        nx_affected.select(["--files", *files]).tasks
        if files and any(ln.nx for ln in lanes)
        else {}
    )
    # A lane reads what detect publishes in CI (TASK_FILES, TYPE_CHECK_PROJECTS, …) from the same nx answer.
    detected = nx_affected.outputs(nx_affected.Selection(tasks=reached))
    lane_env = {**os.environ, **{key.upper(): value for key, value in detected.items()}}

    selected, skipped_pre = select_lanes(lanes, files, reached, args, only, skip)
    results.extend(
        {"name": ln.name, "status": "unchanged" if why == "unchanged" else "skipped", "reason": why}
        for ln, why in skipped_pre
    )
    for ln, why in skipped_pre:
        say(f"  - {ln.name}: {why}")

    if args.dry_run:
        print_plan(selected, len(lanes), args, say)
        return 0
    log_dir.mkdir(parents=True, exist_ok=True)

    results.extend(execute_lanes(selected, root, log_dir, lane_env, args, say))

    total_ms = int((time.monotonic() - t0) * 1000)
    counts = {
        k: sum(1 for r in results if r["status"] == k)
        for k in ("passed", "failed", "unchanged", "skipped", "error", "timeout")
    }
    report = {
        "schema_version": SCHEMA_VERSION,
        "base": base,
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "totalMs": total_ms,
        "changedFileCount": len(files),
        "summary": counts,
        "lanes": results,
        "logDir": str(log_dir.relative_to(root)),
    }

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_summary(results, counts, total_ms, stamp)

    if counts["failed"]:
        return 1
    if counts["error"] or counts["timeout"]:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
