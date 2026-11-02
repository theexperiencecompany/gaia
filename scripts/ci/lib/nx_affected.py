#!/usr/bin/env python3
"""Ask nx which CI checks a change reaches, and write them as detect's outputs.

A CI check is any nx target whose metadata carries `ci.job`: the ci.yml job
that runs it, the commit status it posts as (`ci.check`, `ci.area`), and when
it runs (`ci.events`, `ci.branch`, `ci.reuse`). A task is affected when a file
its inputs name changed. Reached through `changes.sh affected`.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import functools
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
from typing import TypedDict

REPO_ROOT = Path(__file__).resolve().parents[3]
NX_JSON = REPO_ROOT / "nx.json"
# The images build.yml publishes; no ci.yml job runs them, so they carry no ci metadata.
IMAGE_TARGET = "docker:build"
# A check that names no events runs on every one; off CI there is no event.
LOCAL_EVENT = "local"
# The nx-ci-status plugin (tools/nx-ci-status) writes each task's result where this names.
RESULTS_ENV = "NX_CI_TASK_RESULTS"
# changes.sh files' sentinel for "scan the whole tree".
FULL_SCAN = "__FULL__"
# A source input names files by extension (apps/api/**/*.py, **/*.{ts,tsx});
# a config input names one file (pyproject.toml) or a whole tree (scripts/ci/**/*).
SOURCE_GLOB = re.compile(r"(?:^|/)\*\.(\w+|\{[\w,]+\})$")
# Past this many files a scoped list costs more to carry in detect's outputs
# (1 MB per job) than a full scan costs to run.
SCOPED_FILES_MAX = 300
# Every job carries task_files as one env var, and Linux refuses a single env
# string over 128 KiB (MAX_ARG_STRLEN): no process in the job could start.
TASK_FILES_MAX_BYTES = 96 * 1024


@dataclass(frozen=True)
class Check:
    """One CI check: an nx task and its target's `metadata.ci`."""

    task: str
    job: str
    # The commit status it posts as, `ci / <area> / <check>`; None for a task that only gates its job.
    check: str | None
    area: str | None
    events: tuple[str, ...] | None
    branch: str | None
    reuse: bool
    # "nx": run-job runs it; "action" or "step": a workflow step of its job does.
    runner: str
    # Where its command runs, so the paths it prints resolve from the repo root.
    cwd: str | None = None
    # The file a finding that names no file:line is pinned to.
    fallback: str | None = None
    # `parallelism: false`: it rewrites tracked files, so nothing runs beside it.
    exclusive: bool = False
    # It depends on other tasks (a build chain), so it runs in the one shared nx run.
    chained: bool = False

    def runs_on(self, event: str, branch: str | None) -> bool:
        if self.events is not None and event not in self.events:
            return False
        return self.branch is None or self.branch == branch


@dataclass(frozen=True)
class Selection:
    tasks: dict[str, list[dict[str, str]]]


def _project(task: str) -> str:
    return task.split(":", 1)[0]


def _target(task: str) -> str:
    return task.split(":", 1)[1]


def _nx(*args: str) -> str:
    return subprocess.run(
        ["pnpm", "exec", "nx", *args],
        cwd=REPO_ROOT,
        env={**os.environ, "NX_NO_CLOUD": "true", "NX_DAEMON": "false"},
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def _json_after_banner(out: str, opener: str) -> object:
    """Parse nx's JSON, which a plugin's deprecation notice may precede on stdout."""
    return json.loads(out[out.index(opener) :])


@functools.cache
def checks() -> dict[str, Check]:
    """Every CI check in the workspace, by task, read from the project graph."""
    with tempfile.TemporaryDirectory() as scratch:
        graph = Path(scratch) / "graph.json"
        _nx("graph", f"--file={graph}")
        nodes = json.loads(graph.read_text())["graph"]["nodes"]
    found: dict[str, Check] = {}
    for project, node in nodes.items():
        for target, spec in node["data"]["targets"].items():
            ci = (spec.get("metadata") or {}).get("ci") or {}
            if not ci.get("job"):
                continue
            task = f"{project}:{target}"
            found[task] = Check(
                task=task,
                job=ci["job"],
                check=ci.get("check"),
                area=ci.get("area"),
                events=tuple(ci["events"]) if ci.get("events") else None,
                branch=ci.get("branch"),
                reuse=ci.get("reuse", True),
                runner=ci.get("runner", "nx"),
                cwd=(spec.get("options") or {}).get("cwd"),
                fallback=ci.get("fallback"),
                exclusive=spec.get("parallelism") is False,
                chained=bool(spec.get("dependsOn")),
            )
    return found


def tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout
    return [f for f in out.splitlines() if (REPO_ROOT / f).is_file()]


def select(range_args: list[str]) -> Selection:
    known = checks()
    targets = sorted({_target(task) for task in known} | {IMAGE_TARGET})
    out = _nx("affected", "-t", *targets, "--explain=stdout", *range_args)
    explained = _json_after_banner(out, "{")
    assert isinstance(explained, dict)
    affected = explained["affected"]
    return Selection(
        tasks={
            task: reasons
            for task, reasons in affected.items()
            if task in known or _target(task) == IMAGE_TARGET
        }
    )


def exact_runs(tasks: list[str]) -> list[tuple[list[str], list[str]]]:
    """Split tasks into nx run-many calls whose projects × targets is exactly those tasks.

    run-many runs every target on every project it names, so targets go
    together only when they run on the same projects.
    """
    by_target: dict[str, set[str]] = {}
    for task in tasks:
        project, target = task.split(":", 1)
        by_target.setdefault(target, set()).add(project)
    by_projects: dict[frozenset[str], list[str]] = {}
    for target, projects in by_target.items():
        by_projects.setdefault(frozenset(projects), []).append(target)
    return sorted((sorted(projects), sorted(targets)) for projects, targets in by_projects.items())


class TaskResult(TypedDict):
    """One task's result as the nx-ci-status plugin writes it."""

    status: str
    code: int
    output: str


# The nx task statuses that mean the check passed (a cache hit replays a pass).
PASSED = frozenset({"success", "local-cache", "local-cache-kept-existing", "remote-cache"})
# A CPU-slot prefix for a command that uses this many cores ([] off the box's governor).
Wrap = Callable[[int], list[str]]
# Called with each task's result the moment it has one.
OnDone = Callable[[str, TaskResult], None]


def run(tasks: list[str], parallel: int, wrap: Wrap, on_done: OnDone) -> bool:
    """Run exactly `tasks` through nx, hand each result to `on_done` as it lands; True when all pass.

    A task that writes tracked files runs first, alone. Build chains share one
    nx run-many, so a dependency two of them need builds once. Every other task
    runs as its own `nx run`, `parallel` at a time, so its result is not held
    until the slowest check ends. on_done is called under one lock.
    """
    known = checks()
    exclusive = [t for t in tasks if known[t].exclusive]
    chained = [t for t in tasks if known[t].chained and not known[t].exclusive]
    alone = [t for t in tasks if t not in exclusive and t not in chained]
    lock = threading.Lock()

    def report(task: str, result: TaskResult) -> None:
        with lock:
            on_done(task, result)

    # Lists, not generators: all() would stop running checks at the first red one.
    outcomes = [_run_one(t, wrap, report) for t in exclusive]
    if chained:
        outcomes.append(_run_many(chained, parallel, wrap, report))
    with ThreadPoolExecutor(max_workers=max(parallel, 1)) as pool:
        outcomes += list(pool.map(lambda t: _run_one(t, wrap, report), alone))
    return all(outcomes)


def _run_one(task: str, wrap: Wrap, report: OnDone) -> bool:
    proc = subprocess.run(
        [*wrap(1), "pnpm", "exec", "nx", "run", task, "--output-style=stream-without-prefixes"],
        cwd=REPO_ROOT,
        env={**os.environ, "NX_NO_CLOUD": "true"},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        check=False,
    )
    status = "success" if proc.returncode == 0 else "failure"
    report(task, {"status": status, "code": proc.returncode, "output": proc.stdout})
    return proc.returncode == 0


def _run_many(tasks: list[str], parallel: int, wrap: Wrap, report: OnDone) -> bool:
    """Run tasks in nx run-many calls; the nx-ci-status plugin hands back each task's result."""
    passed = True
    with tempfile.TemporaryDirectory() as scratch:
        for index, (projects, targets) in enumerate(exact_runs(tasks)):
            part = Path(scratch) / f"{index}.json"
            proc = subprocess.run(
                [
                    *wrap(parallel), "pnpm", "exec", "nx", "run-many",
                    "-p", ",".join(projects), "-t", ",".join(targets),
                    # stream: static replays a task's output in one write that process.exit() truncates.
                    f"--parallel={parallel}", "--output-style=stream",
                ],
                cwd=REPO_ROOT,
                env={**os.environ, RESULTS_ENV: str(part), "NX_NO_CLOUD": "true"},
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors="replace",
                check=False,
            )  # fmt: skip
            found: dict[str, TaskResult] = json.loads(part.read_text()) if part.is_file() else {}
            for task in (f"{p}:{t}" for p in projects for t in targets):
                # A task nx never started has no result: its run's output is all there is.
                unstarted: TaskResult = {
                    "status": "failure",
                    "code": proc.returncode or 1,
                    "output": proc.stdout,
                }
                report(task, found.get(task) or unstarted)
            passed = passed and proc.returncode == 0
    return passed


def job_tasks(selection: Selection, event: str, branch: str | None) -> dict[str, list[str]]:
    """Each ci.yml job's affected checks that run on this event and branch."""
    known = checks()
    jobs: dict[str, list[str]] = {}
    for task in sorted(selection.tasks):
        check = known.get(task)
        if check and check.runs_on(event, branch):
            jobs.setdefault(check.job, []).append(task)
    return jobs


def release_groups(selection: Selection) -> list[str]:
    """Name the nx.json release groups with an affected image, the images build.yml publishes."""
    groups = json.loads(NX_JSON.read_text())["release"]["groups"]
    built = {_project(task) for task in selection.tasks if _target(task) == "docker:build"}
    if not built:
        return []

    def members(patterns: list[str]) -> list[str]:
        # nx resolves a group's projects (names or tag: patterns) the way -p does.
        out = _json_after_banner(
            _nx("show", "projects", "--projects", ",".join(patterns), "--json"), "["
        )
        assert isinstance(out, list)
        return [str(p) for p in out]

    return sorted(
        name for name, group in groups.items() if built.intersection(members(group["projects"]))
    )


def task_files(selection: Selection) -> dict[str, str | list[str]]:
    """Map each affected task to the changed files it reads, or FULL_SCAN.

    A task reached through a config, manifest or the CI harness rather than a
    source glob changed no file it would be scoped to, so it scans the whole
    tree; so does one whose list outgrows SCOPED_FILES_MAX, and the longest lists
    while the whole map outgrows TASK_FILES_MAX_BYTES.
    """
    scoped: dict[str, str | list[str]] = {}
    for task, reasons in selection.tasks.items():
        files = sorted(r["file"] for r in reasons if _is_source(r))
        whole = len(files) < len(reasons) or len(files) > SCOPED_FILES_MAX
        scoped[task] = FULL_SCAN if whole else files
    # Past the env budget the longest lists become full scans, which only ever check more.
    while len(json.dumps(scoped)) > TASK_FILES_MAX_BYTES:
        longest = max(
            (task for task, files in scoped.items() if files != FULL_SCAN),
            key=lambda task: len(json.dumps(scoped[task])),
        )
        scoped[longest] = FULL_SCAN
    return scoped


def _is_source(reason: dict[str, str]) -> bool:
    return reason.get("kind") == "input-file" and bool(
        SOURCE_GLOB.search(reason.get("pattern", ""))
    )


def outputs(selection: Selection, event: str, branch: str | None) -> dict[str, str]:
    """Build detect's outputs; a job reads each as the same name upper-cased, and ci:local sets them too."""
    jobs = job_tasks(selection, event, branch)
    return {
        "tasks": json.dumps(sorted(selection.tasks)),
        "jobs": json.dumps(sorted(jobs)),
        "job_tasks": json.dumps(jobs),
        "release_groups": json.dumps(release_groups(selection)),
        "task_files": json.dumps(task_files(selection)),
    }


def _first_reason(reasons: list[dict[str, str]]) -> str:
    first = reasons[0]
    more = f" (+{len(reasons) - 1} more)" if len(reasons) > 1 else ""
    return f"{first.get('file') or first['kind']}{more}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--all", action="store_true", help="every task, as on a dispatch")
    scope.add_argument("--base", help="the revision the change is measured from")
    # No --head: nx measures the working tree, uncommitted and untracked files included.
    parser.add_argument("--head")
    parser.add_argument(
        "--files-for",
        metavar="TASK",
        help="print one task's files, or FULL_SCAN; read from $TASK_FILES (detect's) when set",
    )
    opts = parser.parse_args()

    range_args = (
        # One argument per file: Linux caps a single argv entry at 128 KiB.
        ["--files", *tracked_files()]
        if opts.all
        else [f"--base={opts.base}", *([f"--head={opts.head}"] if opts.head else [])]
    )
    if opts.files_for:
        from_detect = os.environ.get("TASK_FILES")
        scoped = json.loads(from_detect) if from_detect else task_files(select(range_args))
        entry = scoped.get(opts.files_for, [])
        sys.stdout.write(
            f"{entry}\n" if isinstance(entry, str) else "".join(f"{f}\n" for f in entry)
        )
        return 0

    selection = select(range_args)
    published = outputs(
        selection,
        os.environ.get("GITHUB_EVENT_NAME", LOCAL_EVENT),
        os.environ.get("GITHUB_REF_NAME"),
    )
    lines = "".join(f"{key}={value}\n" for key, value in published.items())
    sink = os.environ.get("GITHUB_OUTPUT")
    if sink:
        with open(sink, "a", encoding="utf-8") as out:
            out.write(lines)
    else:
        sys.stdout.write(lines)

    print(
        f"::group::{len(selection.tasks)} affected task(s), each with the first file that reached it"
    )
    for task, reasons in sorted(selection.tasks.items()):
        print(f"{task} <- {_first_reason(reasons)}")
    print("::endgroup::")
    jobs = ", ".join(json.loads(published["jobs"])) or "none"
    print(f"affected: {len(selection.tasks)} task(s); jobs with work: {jobs}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
