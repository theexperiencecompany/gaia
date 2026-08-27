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

SCHEMA_VERSION = 1
LANES_FILE = Path(__file__).resolve().parent / "verify-lanes.json"
LOG_ROOT = "verify-logs"


def eprint(*args: str) -> None:
    print(*args, file=sys.stderr, flush=True)


@dataclass
class Lane:
    name: str
    scope_re: re.Pattern[str]
    heavy: bool
    timeout_s: int
    require_cmd: list[str]
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
                    scope_re=re.compile(row["scope"]),
                    heavy=bool(row["heavy"]),
                    timeout_s=int(row["timeout_s"]),
                    require_cmd=list(row.get("require_cmd", [])),
                    command=row["command"],
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
    """--base flag > $GH_BASE > current PR's base via gh > origin/master."""
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


def main() -> int:
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
    args = parser.parse_args()

    try:
        root = Path(
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
    lanes = load_lanes(LANES_FILE)

    if args.list:
        for ln in lanes:
            reqs = "+".join(ln.require_cmd) if ln.require_cmd else "-"
            print(
                f"{ln.name:32} heavy={ln.heavy!s:5} timeout={ln.timeout_s:>5}s requires={reqs:20} {ln.command[:90]}"
            )
        return 0

    only = {s.strip() for s in args.only.split(",") if s.strip()}
    skip = {s.strip() for s in args.skip.split(",") if s.strip()}
    if args.only and not only:
        _die("usage error: --only given but no lane names parsed")
    if args.skip and not skip:
        _die("usage error: --skip given but no lane names parsed")
    unknown = only | skip
    known = {ln.name for ln in lanes}
    missing = unknown - known
    if missing:
        eprint(
            f"usage error: unknown lanes: {sorted(missing)}. `mise ci:local --list` shows the table."
        )
        sys.exit(2)

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

    selected: list[tuple[Lane, list[str]]] = []
    skipped_pre: list[tuple[Lane, str]] = []
    for ln in lanes:
        if only:
            if ln.name not in only:
                continue
        elif ln.name in skip:
            skipped_pre.append((ln, "skipped by --skip"))
            continue
        if not only:
            if ln.heavy and not args.with_heavy:
                skipped_pre.append((ln, "heavy (use --with-heavy)"))
                continue
            matched = [f for f in files if ln.scope_re.search(f)]
            if not matched and not args.all:
                skipped_pre.append((ln, "unchanged"))
                continue
        else:
            matched = [f for f in files if ln.scope_re.search(f)]
        missing_tools = [c for c in ln.require_cmd if not shutil.which(c)]
        if missing_tools:
            skipped_pre.append((ln, f"missing tool(s): {','.join(missing_tools)}"))
            continue
        selected.append((ln, matched))

    for ln, why in skipped_pre:
        status = "unchanged" if why == "unchanged" else "skipped"
        results.append({"name": ln.name, "status": status, "reason": why})
    if skipped_pre and not args.json:
        for ln, why in skipped_pre:
            print(f"  - {ln.name}: {why}")

    if args.dry_run:
        say(f"dry-run: would execute {len(selected)} of {len(lanes)} lanes:")
        for i, (ln, matched) in enumerate(selected, 1):
            extra = f", {len(matched)} matched files" if not args.all else ", --all"
            say(f"  [{i}/{len(selected)}] {ln.name} (timeout {ln.timeout_s}s{extra})")
        say("dry-run: nothing was executed.")
        return 0
    log_dir.mkdir(parents=True, exist_ok=True)

    failures = 0
    errors = 0
    for i, (ln, matched) in enumerate(selected, 1):
        suffix = f" ({len(matched)} matched files)" if not args.all else ""
        detail = (
            f" — {', '.join(matched[:5])}{'…' if len(matched) > 5 else ''}"
            if args.verbose and matched
            else ""
        )
        say(f"[{i}/{len(selected)}] {ln.name}{suffix}{detail} … running (timeout {ln.timeout_s}s)")
        log_file = log_dir / f"{ln.name}.log"
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
        duration_ms = int((time.monotonic() - lane_t0) * 1000)

        icon = {"passed": "pass", "failed": "FAIL", "timeout": "TIMEOUT", "error": "ERROR"}[status]
        say(f"      -> {icon:7} {ln.name} [{duration_ms} ms]" + (f" — {reason}" if reason else ""))
        if status == "failed":
            failures += 1
            tail = Path(log_file).read_text(errors="replace").splitlines()[-40:]
            say(
                "      ┌─ last 40 lines "
                + "─" * 30
                + "\n      │ "
                + "\n      │ ".join(tail)
                + "\n      └"
                + "─" * 48
            )
        elif status in ("error", "timeout"):
            errors += 1

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

    total_ms = int((time.monotonic() - t0) * 1000)
    counts = {
        k: sum(1 for r in results if r["status"] == k)
        for k in ("passed", "failed", "unchanged", "skipped", "error", "timeout")
    }
    finished_at = datetime.now(UTC)

    report = {
        "schema_version": SCHEMA_VERSION,
        "base": base,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "totalMs": total_ms,
        "changedFileCount": len(files),
        "summary": counts,
        "lanes": results,
        "logDir": str(log_dir.relative_to(root)),
    }

    if args.json:
        print(json.dumps(report, indent=2))
    else:
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
        failing = [r["name"] for r in results if r["status"] == "failed"]
        broken = [r["name"] for r in results if r["status"] in ("error", "timeout")]
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

    if failures:
        return 1
    if errors:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
