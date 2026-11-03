#!/usr/bin/env python3
"""mise ci:local — run the CI checks this change reaches, through nx, as CI runs them.

Every check is an nx target whose metadata.ci names its ci.yml job and status
(tools/ci/project.json and the code projects' targets). This selects with the
same nx answer CI's detect publishes and runs the same tasks the same way
(nx_affected.run), so local and CI cannot disagree. A check a workflow step
runs (an action, a live secret) stays CI's and is listed as such.

Usage:
  mise ci:local [--json] [--all] [--only a,b] [--skip a,b] [--with-heavy]
              [--list] [--dry-run] [--base REF]

Exit codes: 0 = every check that ran passed; 1 = a check failed;
            2 = bad usage, or nx could not run a check (not a code verdict).
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ci"))
from lib import nx_affected

SCHEMA_VERSION = 2
LOG_ROOT = "verify-logs"
# A PR's checks run by default; --with-heavy adds the builds, tests and audits.
HEAVY_JOBS = frozenset({"python-audit", "ts-build-test"})
# What a change meets before master: its PR, then the merge queue.
LOCAL_EVENTS = ("pull_request", "merge_group")


def eprint(*args: str) -> None:
    print(*args, file=sys.stderr, flush=True)


def _die(msg: str) -> None:
    eprint(msg)
    sys.exit(2)


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, timeout=30, cwd=root, check=False
    )


def pick_base(root: Path, explicit: str | None) -> str:
    """Resolve the base ref: --base flag > $GH_BASE > current PR's base via gh > origin/master."""
    if explicit:
        return explicit
    env_base = os.environ.get("GH_BASE")
    if env_base:
        return env_base
    try:
        proc = subprocess.run(
            ["gh", "pr", "view", "--json", "baseRefName", "--jq", ".baseRefName"],
            capture_output=True,
            text=True,
            timeout=20,
            cwd=root,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return f"origin/{proc.stdout.strip()}"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return "origin/master"


def changed_files(root: Path, base: str) -> list[str]:
    """List the branch's diff from its merge-base with `base`, plus uncommitted and untracked files."""
    branch = _git(root, "diff", "--name-only", f"{base}...HEAD")
    if branch.returncode != 0:
        _die(f"base '{base}' is unusable ({branch.stderr.strip()[:200]}); pass --base")
    files = branch.stdout.splitlines()
    files += _git(root, "diff", "--name-only", "HEAD").stdout.splitlines()
    files += _git(root, "ls-files", "--others", "--exclude-standard").stdout.splitlines()
    return list(dict.fromkeys(f for f in files if f.strip()))


def local_checks() -> dict[str, list[nx_affected.Check]]:
    """Each check nx runs before master, by its status name."""
    by_name: dict[str, list[nx_affected.Check]] = {}
    for check in nx_affected.checks().values():
        if (
            check.check
            and check.runner == "nx"
            and any(check.runs_on(event, None) for event in LOCAL_EVENTS)
        ):
            by_name.setdefault(check.check, []).append(check)
    return dict(sorted(by_name.items()))


def ci_only_checks() -> list[str]:
    """Name the checks a workflow step runs, which ci:local cannot."""
    return sorted({c.check for c in nx_affected.checks().values() if c.check and c.runner != "nx"})


def _names(raw: str, flag: str, known: dict[str, list[nx_affected.Check]]) -> set[str]:
    names = {s.strip() for s in raw.split(",") if s.strip()}
    if raw and not names:
        _die(f"usage error: {flag} given but no check names parsed")
    missing = names - set(known)
    if missing:
        _die(f"usage error: unknown checks: {sorted(missing)}. `mise ci:local --list` shows them.")
    return names


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run GAIA's CI checks locally, through nx.")
    parser.add_argument("--json", action="store_true", help="emit only the JSON report on stdout")
    parser.add_argument("--all", action="store_true", help="every check, changed or not")
    parser.add_argument("--only", default="", help="comma-separated checks (overrides scoping)")
    parser.add_argument("--skip", default="", help="comma-separated checks to leave out")
    parser.add_argument(
        "--with-heavy", action="store_true", help=f"include {', '.join(sorted(HEAVY_JOBS))}"
    )
    parser.add_argument("--list", action="store_true", help="print every check and exit")
    parser.add_argument("--dry-run", action="store_true", help="show the plan; run nothing")
    parser.add_argument("--base", help="git ref to diff against (default: PR base, origin/master)")
    return parser.parse_args()


def print_table(known: dict[str, list[nx_affected.Check]]) -> None:
    for name, parts in known.items():
        job = parts[0].job
        heavy = " (heavy)" if job in HEAVY_JOBS else ""
        print(f"{name:28} {job + heavy:28} {', '.join(p.task for p in parts)}")
    print(f"\nRun only in CI (a workflow step): {', '.join(ci_only_checks())}")


def plan(
    known: dict[str, list[nx_affected.Check]],
    affected: set[str] | None,
    args: argparse.Namespace,
) -> tuple[dict[str, list[str]], dict[str, str]]:
    """Each check to run and its tasks, and each check left out with why."""
    only = _names(args.only, "--only", known)
    skip = _names(args.skip, "--skip", known)
    run: dict[str, list[str]] = {}
    left_out: dict[str, str] = {}
    for name, parts in known.items():
        tasks = [p.task for p in parts if affected is None or p.task in affected]
        if only and name not in only:
            continue
        if name in skip:
            left_out[name] = "--skip"
        elif not only and parts[0].job in HEAVY_JOBS and not args.with_heavy:
            left_out[name] = "heavy (--with-heavy)"
        elif not tasks:
            left_out[name] = "unchanged"
        else:
            run[name] = tasks
    return run, left_out


def _nx_parallel(root: Path) -> int:
    out = subprocess.run(
        [sys.executable, "scripts/ci/runner.py", "parallel", "--nx"],
        capture_output=True,
        text=True,
        cwd=root,
        check=True,
    ).stdout
    return int(out.strip())


def _outcome(tasks: list[str], results: dict[str, nx_affected.TaskResult]) -> str:
    if any(task not in results for task in tasks):
        return "error"
    return "passed" if all(results[t]["status"] in nx_affected.PASSED for t in tasks) else "failed"


def run_report(
    to_run: dict[str, list[str]],
    left_out: dict[str, str],
    results: dict[str, nx_affected.TaskResult],
    log_dir: Path,
    root: Path,
) -> list[dict[str, object]]:
    """Write each check's log and return one report entry per check, left-out ones included."""
    report: list[dict[str, object]] = []
    for name, check_tasks in to_run.items():
        log_file = log_dir / f"{name}.log"
        log_file.write_text("".join(results[t]["output"] for t in check_tasks if t in results))
        report.append(
            {
                "name": name,
                "status": _outcome(check_tasks, results),
                "tasks": check_tasks,
                "logFile": str(log_file.relative_to(root)),
            }
        )
    return report + [
        {"name": name, "status": "skipped", "reason": why} for name, why in left_out.items()
    ]


def print_summary(report: list[dict[str, object]], counts: dict[str, int], logs: Path) -> None:
    for r in report:
        if r["status"] != "skipped":
            print(f"  {str(r['status']).upper():7} {r['name']}  ({r['logFile']})")
    failing = [str(r["name"]) for r in report if r["status"] in ("failed", "error")]
    print(
        f"\nci:local: {counts['passed']} passed, {counts['failed']} failed, "
        f"{counts['error']} did not run, {counts['skipped']} left out (logs: {logs}/)"
    )
    print(f"CI only (a workflow step runs them): {', '.join(ci_only_checks())}")
    if failing:
        print(f"NEXT: fix them, then: mise ci:local --only {','.join(failing)}")


def main() -> int:
    args = _parse_args()
    root = Path(_git(Path.cwd(), "rev-parse", "--show-toplevel").stdout.strip() or ".")
    known = local_checks()
    if args.list:
        print_table(known)
        return 0

    def say(msg: str) -> None:
        if not args.json:
            print(msg, flush=True)

    base = pick_base(root, args.base)
    files = changed_files(root, base)
    scoped = not (args.all or args.only)
    selection = nx_affected.select(["--files", *files]) if scoped and files else None
    affected = (set(selection.tasks) if selection else set()) if scoped else None
    to_run, left_out = plan(known, affected, args)
    say(f"ci:local: base={base} changed_files={len(files)} checks={len(to_run)} of {len(known)}")
    for name, why in left_out.items():
        say(f"  - {name}: {why}")
    if args.dry_run:
        for name, tasks in to_run.items():
            say(f"  would run {name}: {', '.join(tasks)}")
        return 0

    started_at = datetime.now(UTC)
    t0 = time.monotonic()
    log_dir = root / LOG_ROOT / (started_at.strftime("%Y%m%d-%H%M%S") + f"-{os.getpid()}")
    log_dir.mkdir(parents=True, exist_ok=True)
    # What detect hands a CI job (JOB_TASKS, …, and the task-files file), from the same nx answer.
    answer = selection or nx_affected.Selection(tasks={})
    detected = nx_affected.outputs(answer, LOCAL_EVENTS[0], None)
    os.environ.update({key.upper(): value for key, value in detected.items()})
    task_files = log_dir / "task-files.json"
    task_files.write_text(json.dumps(nx_affected.task_files(answer)))
    os.environ[nx_affected.TASK_FILES_ENV] = str(task_files)
    tasks = [task for check_tasks in to_run.values() for task in check_tasks]
    results: dict[str, nx_affected.TaskResult] = {}

    def on_done(task: str, result: nx_affected.TaskResult) -> None:
        results[task] = result
        say(f"  {'pass' if result['status'] in nx_affected.PASSED else 'FAIL':5} {task}")

    nx_affected.run(tasks, _nx_parallel(root), lambda _cores: [], on_done)

    report = run_report(to_run, left_out, results, log_dir, root)
    counts = {
        k: sum(r["status"] == k for r in report) for k in ("passed", "failed", "error", "skipped")
    }
    summary = {
        "schema_version": SCHEMA_VERSION,
        "base": base,
        "started_at": started_at.isoformat(),
        "totalMs": int((time.monotonic() - t0) * 1000),
        "changedFileCount": len(files),
        "summary": counts,
        "checks": report,
        "ciOnly": ci_only_checks(),
        "logDir": str(log_dir.relative_to(root)),
    }
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print_summary(report, counts, log_dir.relative_to(root))
    if counts["failed"]:
        return 1
    return 2 if counts["error"] else 0


if __name__ == "__main__":
    sys.exit(main())
