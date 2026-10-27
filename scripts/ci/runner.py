#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# ///
"""runner.py — everything about WHERE and HOW HARD a CI job runs.

Subcommands:
  select              Route each runner class to GitHub-hosted, overflowing to
                      the home box once GitHub's queue is saturated and to
                      Blacksmith once the box has no idle listener either. Writes light / heavy / services (runs-on JSON
                      arrays) plus runner / runner_label / is_self_hosted /
                      reason (the heavy class) to $GITHUB_OUTPUT (stdout when
                      unset).
  watchdog            Cancel this run once any job has stayed `queued` past
                      the limit — a box that died after `select` decided.
  requeue-stranded    Force-cancel and fully re-run any re-run attempt whose lanes
                      are stuck queued on the home label while no home
                      runner is online (scheduled: ci-requeue.yml).
  cancel-superseded   Force-cancel older queued/in-progress runs of this workflow
                      on this branch (per-SHA concurrency needs it); on a
                      merge group, every active merge_group run whose head is
                      no longer a live merge-queue entry.
  rescope <workflow>  Re-run the PR head's latest pull_request run of
                      <workflow> in full, force-cancelling it first if it is
                      still going: a retarget (pr-title.yml) re-scopes CI
                      without a run of its own on `edited`.
  prime-archive [dir] Pre-populate the runner's action archive cache with
                      every SHA-pinned `uses:` in .github.
  parallel [flag]     Emit parallelism sized from this runner's CPU/RAM.
                      Flags: --nx --pytest --pytest-n --ruff --mypy --docker
                      --env (default) --json.
  dep-marker <kind>   Print the marker path that decides whether a persisted
                      node|python install is stale.
  heal-venv <dir>     Remove a persisted uv venv that holds no runnable
                      interpreter or no pyvenv.cfg, so uv recreates it.
  with-slots N -- cmd Acquire N host CPU tokens (lib/cpu-slots.sh), run cmd,
                      release them.
  spawn NAME -- cmd   Start cmd in the background so a job's checks run side by
                      side; its log, exit code and step summary are kept apart.
  join NAME           Wait for a spawned check, print its log as a group, append
                      its step summary, annotate a failure, exit with its code.
  health              Print, as JSON, what the box is actually doing: the home
                      listener pool, load average, thread count, who holds CPU
                      slots, and how many mutmut/pytest processes are running.
                      Read-only; never fails.

Env contract:
  every API call      lib/github.py's (token, base URL, timeout, retries).
  select              GITHUB_REPOSITORY, RUNNER_LABEL (heavy, default
                      gaia-home), SERVICES_RUNNER_LABEL (default gaia-home),
                      FALLBACK_RUNNER (default ["ubuntu-latest"]), FORCE_HOME,
                      FORCE_GITHUB, PR_HEAD_REPO, PR_AUTHOR_ASSOCIATION,
                      GITHUB_ACTOR, BLACKSMITH_LABEL, HOSTED_QUEUE_THRESHOLD
                      (5); writes $GITHUB_OUTPUT and $GITHUB_STEP_SUMMARY.
  watchdog            GITHUB_REPOSITORY, GITHUB_RUN_ID, WATCHDOG_JOB_NAME
                      (required), RUNNER_LABEL (gaia-home), QUEUE_LIMIT_SECS
                      (480), POLL_SECS (30), GITHUB_EVENT_NAME,
                      GITHUB_WORKFLOW_REF, GITHUB_HEAD_REF or GITHUB_REF_NAME,
                      DEFAULT_BRANCH (merge_group: where ci-requeue.yml runs).
  requeue-stranded    GITHUB_REPOSITORY, RUNNER_LABEL (gaia-home),
                      QUEUE_LIMIT_SECS (480), CANCEL_WAIT_SECS (180),
                      POLL_SECS (10), REQUEUE_RUN_ID (one handed-over run
                      instead of the sweep).
  cancel-superseded   GITHUB_REPOSITORY, GITHUB_RUN_ID, GITHUB_WORKFLOW_REF,
                      GITHUB_HEAD_REF or GITHUB_REF_NAME, GITHUB_EVENT_NAME,
                      MERGE_GROUP_BASE_REF (merge_group: the queue's branch).
  rescope             GITHUB_REPOSITORY, HEAD_SHA (the PR head), CANCEL_WAIT_SECS
                      (180), POLL_SECS (10).
  prime-archive       ACTIONS_RUNNER_ACTION_ARCHIVE_CACHE, GAIA_REPO
                      (checkout to scan when run from a copy outside the repo).
  parallel            PYTEST_WORKER_GB (1.5) — per-xdist-worker RAM budget.
  spawn / join        RUNNER_TEMP (required: the files live in $RUNNER_TEMP/bg),
                      GITHUB_STEP_SUMMARY (spawn redirects it, join appends).
  health              GITHUB_REPOSITORY, RUNNER_LABEL (gaia-home); reads the
                      cpu-slots pool dir, never takes from it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import datetime
from enum import StrEnum
from functools import cached_property
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import urllib.parse

from lib.github import GitHub, GitHubError, Json, field_of, records, text_of

HERE = Path(__file__).resolve().parent
LOG_SH = HERE / "lib" / "log.sh"
CPU_SLOTS_SH = HERE / "lib" / "cpu-slots.sh"

DEFAULT_REPO = "theexperiencecompany/gaia"
DEFAULT_HOME_LABEL = "gaia-home"
DEFAULT_FALLBACK = '["ubuntu-latest"]'
# GitHub-hosted jobs waiting for a VM at which GitHub counts as saturated. The
# org's Free plan runs 20 hosted jobs at once and a full CI run peaks at 12
# (run 40178782875, every job started within 6 s), so jobs only pile up queued
# once the 20 slots are taken: 5 waiting is the cap already hit, while a lone
# fan-out still being provisioned clears in seconds and rarely reads that high.
HOSTED_SATURATED_QUEUE_DEPTH = 5
TEST_SLICES_JSON = HERE / "lib" / "test-slices.json"
# test-mutation's `max-parallel` in ci.yml: the shards one run holds at once.
MUTATION_WAVE = 6
REQUEUE_WORKFLOW = "ci-requeue.yml"
SELF_HOSTED = "self-hosted"
# The box's runners are gaia-home-<n> (gaia-infra setup.sh RUNNER_NAME_PREFIX); the
# runner kind cannot tell it from Blacksmith, which reports self-hosted too.
BOX_RUNNER_NAME_PREFIX = "gaia-home-"


ACTIVE_RUN_STATUSES = frozenset({"queued", "pending", "waiting", "in_progress"})
# A job wants a GitHub-hosted (or Blacksmith) VM when one of its labels names one.
HOSTED_JOB_LABEL = re.compile(r"^(ubuntu|windows|macos|blacksmith)-")
WORKFLOW_FILE = re.compile(r".*/\.github/workflows/([^@]+)@.*")
USES_LINE = re.compile(
    r"^\s*-?\s*uses:\s*([A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+@[A-Za-z0-9_./-]+)", re.MULTILINE
)
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")


class Die(Exception):
    """A fail-loud stop: printed as one ::error:: line, exit 1."""


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def ok(message: str) -> None:
    print(message, flush=True)


def warn(message: str) -> None:
    log(f"::warning::{message}")


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name) or str(default)
    try:
        return int(raw)
    except ValueError as err:
        raise Die(f"{name}={raw!r} is not an integer") from err


def env_required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise Die(f"{name} is required")
    return value


def repository() -> str:
    return os.environ.get("GITHUB_REPOSITORY") or DEFAULT_REPO


def epoch(stamp: str) -> int:
    """ISO-8601 (…Z) to epoch seconds; an absent stamp is 0."""
    if not stamp:
        return 0
    return int(datetime.datetime.fromisoformat(stamp).timestamp())


def workflow_file() -> str:
    ref = env_required("GITHUB_WORKFLOW_REF")
    match = WORKFLOW_FILE.fullmatch(ref)
    if match is None:
        raise Die(f"GITHUB_WORKFLOW_REF {ref!r} names no .github/workflows file")
    return match.group(1)


def head_branch() -> str:
    return os.environ.get("GITHUB_HEAD_REF") or env_required("GITHUB_REF_NAME")


# ── the home pool ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Pool:
    """One label's runner instances: the home box is a pool, never one instance."""

    label: str
    online: int
    idle: int
    total: int

    def describe(self) -> str:
        return f"{self.idle} idle / {self.online} online / {self.total} registered"


def _runner_labels(runner: Json) -> list[str]:
    return [field_of(label, "name", str) for label in records(runner, "labels")]


def read_pool(gh: GitHub, repo: str, label: str) -> Pool | None:
    """Read the pool carrying the label; None when no instance is registered with it."""
    runners = gh.collect(f"repos/{repo}/actions/runners?per_page=100", "runners")
    matching = [r for r in runners if label in _runner_labels(r)]
    if not matching:
        return None
    online = [r for r in matching if field_of(r, "status", str) == "online"]
    idle = [r for r in online if field_of(r, "busy", bool) is False]
    return Pool(label, len(online), len(idle), len(matching))


class HomeState(StrEnum):
    ONLINE = "online"
    OFFLINE = "offline"
    UNKNOWN = "unknown"


def home_state(gh: GitHub, repo: str, label: str) -> HomeState:
    """Report whether any instance of the label is online; UNKNOWN is never a reason to act."""
    try:
        pool = read_pool(gh, repo, label)
    except GitHubError as err:
        log(f"runners probe failed ({err}) — cannot say whether '{label}' is alive")
        return HomeState.UNKNOWN
    online = pool.online if pool else 0
    log(f"{online} runner(s) online with label '{label}'")
    return HomeState.ONLINE if online else HomeState.OFFLINE


# ── select ────────────────────────────────────────────────────────────────


def _queued_jobs(gh: GitHub, repo: str, run: Json) -> list[Json]:
    run_id = field_of(run, "id", int)
    jobs = records(gh.get(f"repos/{repo}/actions/runs/{run_id}/jobs?per_page=100"), "jobs")
    return [j for j in jobs if field_of(j, "status", str) == "queued"]


def _job_labels(job: Json) -> list[str]:
    labels = job.get("labels") or []
    if not isinstance(labels, list) or not all(isinstance(x, str) for x in labels):
        raise GitHubError("job 'labels' is not a list of strings")
    return [str(x) for x in labels]


def _sampled_runs(gh: GitHub, repo: str, status: str, per_page: int) -> list[Json]:
    """Sample runs, bounded: enough to see a real backlog inside a 2-minute job."""
    return records(
        gh.get(f"repos/{repo}/actions/runs?status={status}&per_page={per_page}"), "workflow_runs"
    )


def hosted_queue_depth(gh: GitHub, repo: str) -> int:
    """Jobs waiting for a GitHub-hosted VM: queued runs plus the queued jobs of started ones."""
    runs = _sampled_runs(gh, repo, "queued", 10) + _sampled_runs(gh, repo, "in_progress", 5)
    return sum(
        1
        for run in runs
        for job in _queued_jobs(gh, repo, run)
        if any(HOSTED_JOB_LABEL.match(label) for label in _job_labels(job))
    )


class RunnerClass(StrEnum):
    LIGHT = "light"
    HEAVY = "heavy"
    SERVICES = "services"


def class_demand() -> dict[RunnerClass, int]:
    """Count the listeners one full run holds at once per class; a class shares one label."""
    slices = records(json.loads(TEST_SLICES_JSON.read_text()), "slices")
    with_services = sum(1 for s in slices if field_of(s, "services", str) == "true")
    return {
        # detect, lint-node, lint-python, lint-mixed, python-audit, scan
        RunnerClass.LIGHT: 6,
        # probe, ts-build-test, docker-image, plus the slices that need no services
        RunnerClass.HEAVY: 3 + len(slices) - with_services,
        # the slices that need services (test-python, test-python-engines), test-mutation's wave
        RunnerClass.SERVICES: with_services + MUTATION_WAVE,
    }


# The order the box's idle listeners are handed out: the slowest lanes first.
OVERFLOW_ORDER = (RunnerClass.SERVICES, RunnerClass.HEAVY, RunnerClass.LIGHT)


@dataclass(frozen=True)
class Choice:
    runs_on: tuple[str, ...]
    label: str
    reason: str
    note: str

    @property
    def is_self_hosted(self) -> bool:
        return SELF_HOSTED in self.runs_on

    def runs_on_json(self) -> str:
        return json.dumps(list(self.runs_on), separators=(",", ":"))


def _fallback_runner() -> tuple[str, ...]:
    raw = os.environ.get("FALLBACK_RUNNER") or DEFAULT_FALLBACK
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as err:
        raise Die(f"FALLBACK_RUNNER {raw!r} is not a JSON array") from err
    if not isinstance(value, list) or not value or not all(isinstance(v, str) for v in value):
        raise Die(f"FALLBACK_RUNNER {raw!r} is not a non-empty JSON array of labels")
    return tuple(value)


def trust_gate(repo: str) -> tuple[str, str] | None:
    """Return why the box is off-limits before any probe, with its summary note."""
    head = os.environ.get("PR_HEAD_REPO", "")
    association = os.environ.get("PR_AUTHOR_ASSOCIATION", "")
    actor = os.environ.get("GITHUB_ACTOR", "")
    # Fork code never runs on the box: its workspace, caches and network are
    # shared state, and this is a public repo.
    if head and head != repo:
        return "fork", f"PR head `{head}` is not `{repo}`; fork code never runs on the home box"
    # Only organisation members' PRs; a push carries no association and needs write access.
    if association and association not in {"OWNER", "MEMBER"}:
        return "untrusted-author", f"PR author association is `{association}`, not OWNER/MEMBER"
    # Bots run unreviewed postinstall scripts from their dependency bumps.
    if actor.endswith("[bot]"):
        return "bot-actor", f"actor `{actor}` is a bot; bots never run on the home box"
    if os.environ.get("FORCE_GITHUB") == "true":
        return "forced-github", "`force_github` set on this dispatch"
    return None


@dataclass
class Router:
    """One select invocation: GitHub-hosted first, the box as overflow, Blacksmith last.

    Every probe runs at most once and is shared by the classes. The box is
    reached only once GitHub's own queue is saturated: under load a box job
    waited up to 48 min while an all-GitHub run waited at most 6 s per job.
    """

    gh: GitHub
    repo: str
    fallback: tuple[str, ...]
    force_home: bool
    blacksmith: str
    threshold: int
    pools: dict[str, Pool | None | GitHubError] = field(default_factory=dict)
    claimed: dict[str, int] = field(default_factory=dict)

    def fallback_choice(self, reason: str, note: str) -> Choice:
        return Choice(self.fallback, self.fallback[0], reason, note)

    @cached_property
    def hosted_depth(self) -> int | None:
        """GitHub's own backlog, or None when it could not be read (never 0)."""
        try:
            depth = hosted_queue_depth(self.gh, self.repo)
        except GitHubError as err:
            warn(
                f"hosted queue probe failed ({err}) — staying on the free GitHub-hosted "
                "runners rather than overflowing blind."
            )
            return None
        log(f"[select-runner] hosted queue depth: {depth} job(s) (saturated at {self.threshold})")
        return depth

    def pool(self, label: str) -> Pool | None:
        if label not in self.pools:
            try:
                self.pools[label] = read_pool(self.gh, self.repo, label)
            except GitHubError as err:
                warn(f"runners API unavailable ({err}) — cannot see `{label}`'s listeners")
                self.pools[label] = err
        reading = self.pools[label]
        if isinstance(reading, GitHubError):
            raise reading
        return reading

    def route(self, label: str, demand: int) -> Choice:
        if self.force_home:
            return self._forced_home(label)
        depth = self.hosted_depth
        if depth is None:
            return self.fallback_choice("hosted-queue-unknown", "GitHub queue unreadable")
        if depth < self.threshold:
            return self.fallback_choice("github-hosted", f"GitHub queue {depth} < {self.threshold}")
        return self._overflow(label, demand, f"GitHub queue {depth} >= {self.threshold}")

    def _overflow(self, label: str, demand: int, saturated: str) -> Choice:
        """Take the box only when every job of the class gets its own idle listener."""
        try:
            pool = self.pool(label)
        except GitHubError:
            return self._last_resort(f"{saturated}; `{label}` unreadable")
        if pool is None:
            return self._last_resort(f"{saturated}; no runner with label `{label}` registered")
        free = pool.idle - self.claimed.get(label, 0)
        note = f"{saturated}; `{label}`: {pool.describe()}, {free} free for {demand} job(s)"
        if free >= demand:
            self.claimed[label] = self.claimed.get(label, 0) + demand
            return Choice((SELF_HOSTED, label), label, "home-overflow", note)
        return self._last_resort(note)

    def _last_resort(self, note: str) -> Choice:
        if not self.blacksmith:
            return self.fallback_choice("github-queued", f"{note}; Blacksmith not configured")
        return Choice((self.blacksmith,), self.blacksmith, "blacksmith-overflow", note)

    def _forced_home(self, label: str) -> Choice:
        try:
            pool = self.pool(label)
        except GitHubError as err:
            raise Die(f"HOME runner forced but the runners API probe failed ({err})") from err
        if pool is None:
            raise Die(f"HOME runner forced but no runner with label {label} is registered")
        if not pool.online:
            raise Die(f"HOME runner forced but `{label}` is offline ({pool.describe()})")
        return Choice((SELF_HOSTED, label), label, "forced-home", f"`{label}`: {pool.describe()}")


def route() -> dict[RunnerClass, Choice]:
    repo = repository()
    fallback = _fallback_runner()
    gate = trust_gate(repo)
    gh = GitHub.from_env()
    if gate is None and not gh.token:
        gate = ("no-token", "no API token available (local run)")
    if gate is not None:
        reason, note = gate
        same = Choice(fallback, fallback[0], reason, note)
        return dict.fromkeys(RunnerClass, same)
    router = Router(
        gh=gh,
        repo=repo,
        fallback=fallback,
        force_home=os.environ.get("FORCE_HOME") == "true",
        blacksmith=os.environ.get("BLACKSMITH_LABEL", ""),
        threshold=env_int("HOSTED_QUEUE_THRESHOLD", HOSTED_SATURATED_QUEUE_DEPTH),
    )
    home = os.environ.get("RUNNER_LABEL") or DEFAULT_HOME_LABEL
    labels = dict.fromkeys(RunnerClass, home)
    labels[RunnerClass.SERVICES] = os.environ.get("SERVICES_RUNNER_LABEL") or DEFAULT_HOME_LABEL
    demand = class_demand()
    routed = {cls: router.route(labels[cls], demand[cls]) for cls in OVERFLOW_ORDER}
    return {cls: routed[cls] for cls in RunnerClass}


def cmd_select(_args: list[str]) -> int:
    choices = route()
    heavy = choices[RunnerClass.HEAVY]
    lines = [
        f"runner_label={heavy.label}",
        f"is_self_hosted={str(heavy.is_self_hosted).lower()}",
        f"reason={heavy.reason}",
        *(f"{cls.value}={choice.runs_on_json()}" for cls, choice in choices.items()),
    ]
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    else:
        print("\n".join(lines))
    summary = [
        "### Runner selection",
        "",
        "| class | runs-on | reason | why |",
        "| --- | --- | --- | --- |",
        *(
            f"| {cls.value} | `{c.runs_on_json()}` | {c.reason} | {c.note} |"
            for cls, c in choices.items()
        ),
    ]
    log("[select-runner] " + "\n".join(summary))
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY", "")
    if summary_file and Path(summary_file).is_file():
        with open(summary_file, "a", encoding="utf-8") as handle:
            handle.write("\n".join(summary) + "\n")
    return 0


# ── watchdog ──────────────────────────────────────────────────────────────

# A box that dies after select leaves self-hosted jobs queued for up to 24 h.
# Age runs from ELIGIBILITY (creation or the run's last progress, whichever is
# later); a busy box and an unreadable runners probe both mean keep waiting.


@dataclass(frozen=True)
class Job:
    name: str
    status: str
    created: int
    progress: int

    @classmethod
    def parse(cls, doc: Json) -> Job:
        stamps = [epoch(text_of(doc, "started_at")), epoch(text_of(doc, "completed_at"))]
        return cls(
            name=field_of(doc, "name", str),
            status=field_of(doc, "status", str),
            created=epoch(text_of(doc, "created_at")),
            progress=max(stamps),
        )


def _stalled_job(jobs: list[Job], limit: int) -> str:
    last_progress = max((j.progress for j in jobs), default=0)
    now = int(time.time())
    stalled = ""
    for job in (j for j in jobs if j.status == "queued"):
        age = now - max(job.created, last_progress)
        ok(f"watchdog: '{job.name}' eligible for {age}s (limit {limit}s)")
        if age > limit:
            stalled = job.name
    return stalled


def _hand_to_requeue(gh: GitHub, stalled: str, limit: int, label: str) -> int:
    """Have ci-requeue.yml cancel and re-run this run; a run cannot re-run itself."""
    run_id, branch = env_required("GITHUB_RUN_ID"), env_required("DEFAULT_BRANCH")
    ok(
        f"::warning::'{stalled}' has been queued past {limit}s and no runner labelled '{label}' "
        f"is online — handing run {run_id} to {REQUEUE_WORKFLOW} to force-cancel and re-run in "
        "full: quality-gate reports nothing until the re-run's gate does, so the group stays "
        "queued while that lands inside the merge queue's check timeout."
    )
    gh.post(
        f"repos/{repository()}/actions/workflows/{REQUEUE_WORKFLOW}/dispatches",
        {"ref": branch, "inputs": {"run_id": run_id}},
    )
    return 0


def _redispatch_or_cancel(gh: GitHub, run: str, stalled: str, limit: int, label: str) -> int:
    """Re-dispatch the workflow onto GitHub for a dead box, then cancel this run."""
    event = os.environ.get("GITHUB_EVENT_NAME")
    if event == "workflow_dispatch":
        # Already the fallback: if IT stalls there is nothing left to try.
        ok(
            f"::error::'{stalled}' has been queued past {limit}s on the GitHub fallback too — giving up."
        )
        gh.post(f"{run}/cancel")
        return 1
    if event == "merge_group":
        # A dispatch on the gh-readonly-queue ref reports to no merge-group check suite.
        return _hand_to_requeue(gh, stalled, limit, label)
    workflow, branch = workflow_file(), head_branch()
    ok(
        f"::warning::'{stalled}' has been queued past {limit}s and no runner labelled '{label}' "
        f"is online — re-dispatching {workflow} on {branch} with force_github=true instead of "
        "leaving this PR without a verdict."
    )
    try:
        gh.post(
            f"repos/{repository()}/actions/workflows/{workflow}/dispatches",
            {"ref": branch, "inputs": {"force_github": "true"}},
        )
    except GitHubError as err:
        ok(
            f"::error::could not re-dispatch {workflow} on {branch} ({err}) — cancelling; "
            "re-run with force_github=true to use GitHub-hosted runners."
        )
        gh.post(f"{run}/cancel")
        return 1
    gh.post(f"{run}/cancel")
    return 0


def _watch_once(gh: GitHub, run: str, me: str, limit: int, label: str) -> int | None:
    """One poll; an exit code when the watch is over, None to keep watching."""
    status = field_of(gh.get(run), "status", str)
    if status not in ACTIVE_RUN_STATUSES:
        ok(f"watchdog: run is {status} — nothing left to watch")
        return 0
    jobs = [Job.parse(j) for j in gh.collect(f"{run}/jobs?per_page=100", "jobs")]
    jobs = [j for j in jobs if j.name != me]
    if not any(j.status == "queued" for j in jobs):
        if not jobs:
            # Lanes whose `needs:` have not resolved have no record yet.
            ok(f"watchdog: no lanes created yet (run {status}) — waiting")
            return None
        live = any(j.status != "completed" for j in jobs)
        ok(
            "watchdog: no queued jobs — every lane was picked up"
            if live
            else "watchdog: every lane finished"
        )
        return 0
    stalled = _stalled_job(jobs, limit)
    if not stalled:
        return None
    match home_state(gh, repository(), label):
        case HomeState.ONLINE:
            warn(
                f"'{stalled}' has been queued for over {limit}s, but instances labelled "
                f"'{label}' are online — the box is busy, not dead. Not cancelling."
            )
        case HomeState.UNKNOWN:
            warn(
                f"'{stalled}' has been queued for over {limit}s and the runners API could "
                "not be probed — not cancelling on an unknown."
            )
        case HomeState.OFFLINE:
            return _redispatch_or_cancel(gh, run, stalled, limit, label)
    return None


def cmd_watchdog(_args: list[str]) -> int:
    limit = env_int("QUEUE_LIMIT_SECS", 480)
    poll = env_int("POLL_SECS", 30)
    label = os.environ.get("RUNNER_LABEL") or DEFAULT_HOME_LABEL
    me = env_required("WATCHDOG_JOB_NAME")
    run = f"repos/{env_required('GITHUB_REPOSITORY')}/actions/runs/{env_required('GITHUB_RUN_ID')}"
    gh = GitHub.from_env()
    while (code := _watch_once(gh, run, me, limit, label)) is None:
        time.sleep(poll)
    return code


# ── requeue-stranded ──────────────────────────────────────────────────────

# Re-run lanes keep the home runs-on select chose, so they queue forever on a
# dead box. A queued job ignores timeout-minutes, and GitHub re-runs neither a
# job nor a run until the run completes (403 "already running"), so the run
# must be cancelled first. Always force-cancel: a plain cancel still runs the
# `if: always()` quality-gate, which concludes failure and drops a merge group
# from the queue; force-cancel runs no further job (run 40057428378).


def _wait_completed(gh: GitHub, run: str, wait: int, poll: int) -> bool:
    deadline = time.monotonic() + wait
    while (status := field_of(gh.get(run), "status", str)) != "completed":
        if time.monotonic() >= deadline:
            log(f"requeue-stranded: {run} still {status} after {wait}s")
            return False
        time.sleep(poll)
    return True


def _requeue(gh: GitHub, run: str, wait: int, poll: int) -> bool:
    gh.post(f"{run}/force-cancel")
    if not _wait_completed(gh, run, wait, poll):
        return False
    gh.post(f"{run}/rerun")
    return True


def _stranded_job(gh: GitHub, repo: str, run_id: int, label: str, limit: int) -> str:
    now = int(time.time())
    jobs = gh.collect(f"repos/{repo}/actions/runs/{run_id}/jobs?per_page=100", "jobs")
    stranded = ""
    for job in jobs:
        queued_here = field_of(job, "status", str) == "queued" and label in _job_labels(job)
        if queued_here and now - epoch(text_of(job, "created_at")) > limit:
            stranded = field_of(job, "name", str)
    return stranded


def _requeue_candidates(gh: GitHub, repo: str) -> list[int]:
    """Return the run a watchdog handed over, else every in-flight re-run attempt."""
    if handed_over := os.environ.get("REQUEUE_RUN_ID"):
        return [int(handed_over)]
    return [
        field_of(run, "id", int)
        for status in ("queued", "in_progress")
        for run in gh.collect(
            f"repos/{repo}/actions/runs?per_page=100&status={status}", "workflow_runs"
        )
        if field_of(run, "run_attempt", int) > 1
    ]


def cmd_requeue_stranded(_args: list[str]) -> int:
    limit = env_int("QUEUE_LIMIT_SECS", 480)
    label = os.environ.get("RUNNER_LABEL") or DEFAULT_HOME_LABEL
    wait = env_int("CANCEL_WAIT_SECS", 180)
    poll = env_int("POLL_SECS", 10)
    repo = env_required("GITHUB_REPOSITORY")
    gh = GitHub.from_env()
    match home_state(gh, repo, label):
        case HomeState.ONLINE:
            ok(f"requeue-stranded: runners labelled '{label}' are online — nothing is stranded")
            return 0
        case HomeState.UNKNOWN:
            warn(
                "requeue-stranded: the runners API could not be probed — not touching any run on an unknown"
            )
            return 0
    failed = 0
    for run_id in _requeue_candidates(gh, repo):
        stranded = _stranded_job(gh, repo, run_id, label, limit)
        if not stranded:
            continue
        ok(
            f"requeue-stranded: run {run_id}: '{stranded}' queued on '{label}' past {limit}s with "
            f"no '{label}' runner online — force-cancelling to re-run in full"
        )
        if _requeue(gh, f"repos/{repo}/actions/runs/{run_id}", wait, poll):
            ok(f"requeue-stranded: run {run_id} re-run in full — select-runner decides afresh")
        else:
            ok(
                f"::error::run {run_id} was force-cancelled but has not completed "
                f"after {wait}s — re-run it in full by hand once it completes"
            )
            failed = 1
    return failed


# ── cancel-superseded ─────────────────────────────────────────────────────

# Not concurrency.cancel-in-progress: a shared group makes the new run wait out
# the old one's cancel, and a cancelled pytest step on the box wedges the
# listener for its 5-minute timeout. Per-SHA groups plus this async cancel.
# A merge group's ref is new on every queue rebuild, so no branch or
# concurrency group links a stale group's runs to the live one: the queue does.
# Force-cancel, as in requeue-stranded: a plain cancel still runs the old run's
# always() gate and deploy plan, whose build.yml call took the one pending slot
# of build.yml's group from the newest run's build phase (run 40226045729).

MERGE_QUEUE_QUERY = """
query($owner: String!, $name: String!, $branch: String!) {
  repository(owner: $owner, name: $name) {
    mergeQueue(branch: $branch) {
      entries(first: 100) { totalCount nodes { headCommit { oid } } }
    }
  }
}
"""
# GitHub's answer when the run completed between the listing and the cancel.
CANCEL_ALREADY_COMPLETED = 409


def _cancel(gh: GitHub, repo: str, run_id: int, why: str) -> None:
    try:
        gh.post(f"repos/{repo}/actions/runs/{run_id}/force-cancel")
    except GitHubError as err:
        if err.status != CANCEL_ALREADY_COMPLETED:
            raise
        ok(f"run {run_id} completed before its cancel landed")
        return
    ok(f"cancelled {why} run {run_id}")


def _cancel_superseded_branch_runs(gh: GitHub, repo: str, run_id: int) -> None:
    workflow, branch = workflow_file(), head_branch()
    query = urllib.parse.urlencode(
        {"branch": branch, "event": os.environ.get("GITHUB_EVENT_NAME", ""), "per_page": 50}
    )
    runs = gh.collect(f"repos/{repo}/actions/workflows/{workflow}/runs?{query}", "workflow_runs")
    older = [
        field_of(r, "id", int)
        for r in runs
        if field_of(r, "id", int) < run_id and field_of(r, "status", str) in ACTIVE_RUN_STATUSES
    ]
    if not older:
        ok(f"no superseded {workflow} runs on {branch}")
    for old in older:
        _cancel(gh, repo, old, "superseded")


def _live_queue_heads(gh: GitHub, repo: str) -> set[str]:
    owner, name = repo.split("/", 1)
    branch = env_required("MERGE_GROUP_BASE_REF").removeprefix("refs/heads/")
    data = gh.graphql(MERGE_QUEUE_QUERY, {"owner": owner, "name": name, "branch": branch})
    queue = field_of(field_of(data, "repository", dict), "mergeQueue", dict)
    entries = field_of(queue, "entries", dict)
    nodes = records(entries, "nodes")
    if field_of(entries, "totalCount", int) != len(nodes):
        raise GitHubError(f"the {branch} merge queue holds more entries than one page reads")
    return {
        field_of(head, "oid", str)
        for node in nodes
        if isinstance(head := node.get("headCommit"), dict)
    }


def _cancel_dead_merge_groups(gh: GitHub, repo: str, run_id: int) -> None:
    # Runs before the queue: a group created in between is then missing from the
    # listing, instead of listed yet absent from an older queue snapshot.
    runs = [
        run
        for status in sorted(ACTIVE_RUN_STATUSES)
        for run in gh.collect(
            f"repos/{repo}/actions/runs?event=merge_group&status={status}&per_page=100",
            "workflow_runs",
        )
    ]
    live = _live_queue_heads(gh, repo)
    dead = [
        field_of(r, "id", int)
        for r in runs
        if field_of(r, "id", int) != run_id and field_of(r, "head_sha", str) not in live
    ]
    if not dead:
        ok(f"every active merge_group run belongs to one of {len(live)} live queue entries")
    for stale in dead:
        _cancel(gh, repo, stale, "dead merge-group")


def cmd_cancel_superseded(_args: list[str]) -> int:
    repo = env_required("GITHUB_REPOSITORY")
    run_id = env_int("GITHUB_RUN_ID", 0)
    gh = GitHub.from_env()
    if os.environ.get("GITHUB_EVENT_NAME") == "merge_group":
        _cancel_dead_merge_groups(gh, repo, run_id)
    else:
        _cancel_superseded_branch_runs(gh, repo, run_id)
    return 0


# ── rescope ───────────────────────────────────────────────────────────────

# ci.yml does not run on `edited`: that run created every job's check row and
# replaced the commit's real ones with "Skipped". A re-run keeps the original
# payload, which is fine: detect resolves the base from the API
# (`changes.sh base`), and a re-run attempt reuses no earlier pass.


def cmd_rescope(args: list[str]) -> int:
    if len(args) != 1:
        raise Die("usage: runner.py rescope <workflow file>")
    repo, sha = env_required("GITHUB_REPOSITORY"), env_required("HEAD_SHA")
    query = urllib.parse.urlencode({"head_sha": sha, "event": "pull_request", "per_page": 1})
    gh = GitHub.from_env()
    runs = records(
        gh.get(f"repos/{repo}/actions/workflows/{args[0]}/runs?{query}"), "workflow_runs"
    )
    if not runs:
        ok(f"rescope: no {args[0]} run on {sha} yet — the one its push starts reads the new base")
        return 0
    run_id = field_of(runs[0], "id", int)
    run = f"repos/{repo}/actions/runs/{run_id}"
    if field_of(runs[0], "status", str) == "completed":
        gh.post(f"{run}/rerun")
    elif not _requeue(gh, run, env_int("CANCEL_WAIT_SECS", 180), env_int("POLL_SECS", 10)):
        ok(
            f"::error::rescope: run {run_id} was force-cancelled but has not completed — "
            "re-run it in full by hand once it does, or push, so CI checks the new base"
        )
        return 1
    ok(f"rescope: run {run_id} re-run in full against the PR's new base")
    return 0


# ── prime-archive ─────────────────────────────────────────────────────────

# The runner only READS $ACTIONS_RUNNER_ACTION_ARCHIVE_CACHE/<owner>_<repo>/<sha>.tar.gz,
# so each job re-downloaded the same pins (~20 s). A miss is a warning: the
# archive is only a shortcut.


def _pinned_actions(root: Path) -> list[str]:
    refs: set[str] = set()
    for path in (root / ".github").rglob("*"):
        if path.is_file():
            refs.update(USES_LINE.findall(path.read_text(errors="replace")))
    return sorted(refs)


def _prime_one(gh: GitHub, cache: Path, ref: str) -> bool | None:
    """Fetch one action tarball: True fetched, False already present, None unobtainable."""
    slug, want = ref.rsplit("@", 1)
    repo = "/".join(slug.split("/")[:2])
    try:
        sha = (
            want
            if FULL_SHA.match(want)
            else field_of(gh.get(f"repos/{repo}/commits/{want}"), "sha", str)
        )
    except GitHubError as err:
        warn(f"could not resolve {repo}@{want} — {err}")
        return None
    target = cache / repo.replace("/", "_") / f"{sha}.tar.gz"
    if target.is_file() and target.stat().st_size > 0:
        return False
    try:
        tarball = gh.get_bytes(f"repos/{repo}/tarball/{sha}")
    except GitHubError as err:
        warn(f"could not fetch {repo}@{sha} — {err}")
        return None
    if not tarball:
        warn(f"could not fetch {repo}@{sha} — empty tarball")
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    partial.write_bytes(tarball)
    partial.replace(target)
    ok(f"fetched {repo}@{sha}")
    return True


def cmd_prime_archive(args: list[str]) -> int:
    default_cache = Path.home() / "ci-cache" / "actions-archive"
    cache = Path(
        args[0] if args else os.environ.get("ACTIONS_RUNNER_ACTION_ARCHIVE_CACHE") or default_cache
    )
    root = Path(os.environ.get("GAIA_REPO") or HERE.parent.parent)
    if not (root / ".github").is_dir():
        raise Die(f"no workflows under {root} (set GAIA_REPO)")
    cache.mkdir(parents=True, exist_ok=True)
    gh = GitHub.from_env()
    results = [_prime_one(gh, cache, ref) for ref in _pinned_actions(root)]
    ok(f"action archive: {results.count(False)} present, {results.count(True)} fetched → {cache}")
    return 0


# ── parallel ──────────────────────────────────────────────────────────────

GIB_KB = 1024 * 1024
PER_WORKER_GB_DEFAULT = "1.5"  # measured peak 1.04-1.05 GB/worker with the embedding sidecar
HEADROOM_GB = 4  # OS, docker, the runner agent, the coordinating pytest process
MIN_CPU_WORKERS = 4
BIG_HOST_THREADS = 14
MID_HOST_THREADS = 7
LOW_MEM_BIG_HOST_GB = 12
BIG_HOST_NX = 6  # benchmark run 33108678517: --parallel 4 42s, 8 59s; 6 leaves room for a lane
LOW_MEM_BIG_HOST_NX = 8
SMALL_HOST_NX = 3
SMALL_HOST_DOCKER = 2


def _nproc() -> int:
    if hasattr(os, "sched_getaffinity"):
        return len(os.sched_getaffinity(0))
    return os.cpu_count() or 2


def _memory_gb() -> tuple[int, int]:
    """Total and currently-available GiB: available, because several runners share the box."""
    meminfo = Path("/proc/meminfo")
    if meminfo.is_file():
        fields = dict(
            line.split(":", 1) for line in meminfo.read_text().splitlines() if ":" in line
        )
        total = int(fields["MemTotal"].split()[0]) // GIB_KB
        return total, int(fields["MemAvailable"].split()[0]) // GIB_KB
    total = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") // (1024**3)
    log("detect-parallel: no /proc/meminfo — treating total memory as available")
    return total, total


def _running_xdist_workers() -> int:
    proc = Path("/proc")
    if not proc.is_dir():
        return 0
    count = 0
    for cmdline in proc.glob("[0-9]*/cmdline"):
        try:
            args = cmdline.read_bytes().replace(b"\0", b" ")
        except OSError:
            continue  # the process exited between the listing and the read
        if b"[pytest-xdist" in args and cmdline.parent.name != str(os.getpid()):
            count += 1
    return count


@dataclass(frozen=True)
class Parallelism:
    nproc: int
    mem_gb: int
    mem_avail_gb: int
    nx: int
    pytest_n: int
    pytest_capped: bool
    docker: int

    @property
    def pytest(self) -> str:
        return str(self.pytest_n) if self.pytest_capped else "auto"

    def env(self) -> str:
        pairs = {
            "NX_PARALLEL": self.nx,
            "PYTEST_XDIST": self.pytest,
            "PYTEST_XDIST_N": self.pytest_n,
            "RUFF_JOBS": self.nproc,
            "MYPY_JOBS": self.nproc,
            "DOCKER_JOBS": self.docker,
            "NPROC": self.nproc,
            "MEM_GB": self.mem_gb,
            "MEM_AVAIL_GB": self.mem_avail_gb,
        }
        return "\n".join(f"{k}={v}" for k, v in pairs.items())

    def as_json(self) -> str:
        doc = {
            "nproc": self.nproc,
            "mem_gb": self.mem_gb,
            "nx_parallel": self.nx,
            "pytest_xdist": self.pytest,
            "pytest_xdist_n": self.pytest_n,
            "ruff_jobs": self.nproc,
            "mypy_jobs": self.nproc,
            "docker_jobs": self.docker,
        }
        return json.dumps(doc, separators=(",", ":"))


def measure_parallelism() -> Parallelism:
    nproc = _nproc()
    mem_gb, mem_avail_gb = _memory_gb()
    if nproc >= BIG_HOST_THREADS:
        nx = LOW_MEM_BIG_HOST_NX if mem_gb < LOW_MEM_BIG_HOST_GB else BIG_HOST_NX
        pytest_n, docker = 16, nproc
    elif nproc >= MID_HOST_THREADS:
        nx, pytest_n, docker = nproc, nproc, nproc
    else:
        nx, pytest_n, docker = SMALL_HOST_NX, nproc, SMALL_HOST_DOCKER
    capped = False
    # Lanes landing together share the cores instead of fighting for them.
    running = _running_xdist_workers()
    cpu_workers = max(nproc - running, MIN_CPU_WORKERS)
    if cpu_workers < pytest_n:
        log(
            f"detect-parallel: cpu-capped pytest workers {pytest_n} -> {cpu_workers} "
            f"({running} xdist workers already running on this host)"
        )
        pytest_n, capped = cpu_workers, True
    per_worker = float(os.environ.get("PYTEST_WORKER_GB") or PER_WORKER_GB_DEFAULT)
    mem_workers = max(int((mem_avail_gb - HEADROOM_GB) / per_worker), 1)
    if mem_workers < pytest_n:
        log(
            f"detect-parallel: memory-capped pytest workers {pytest_n} -> {mem_workers} "
            f"({mem_avail_gb}G available, {per_worker:g}G/worker)"
        )
        pytest_n, capped = mem_workers, True
    return Parallelism(nproc, mem_gb, mem_avail_gb, nx, pytest_n, capped, docker)


def cmd_parallel(args: list[str]) -> int:
    flag = args[0] if args else "--env"
    views: dict[str, Callable[[Parallelism], object]] = {
        "--nx": lambda p: p.nx,
        "--pytest": lambda p: p.pytest,
        "--pytest-n": lambda p: p.pytest_n,
        "--ruff": lambda p: p.nproc,
        "--mypy": lambda p: p.nproc,
        "--docker": lambda p: p.docker,
        "--env": Parallelism.env,
        "--json": Parallelism.as_json,
    }
    if flag not in views:
        log(f"unknown arg {flag}")
        return 1
    print(views[flag](measure_parallelism()))
    return 0


# ── dep-marker / heal-venv ────────────────────────────────────────────────
# The one place that decides when a persisted install is stale. The key covers
# EVERY input that changes what the install produces, not just the lockfile.

DEP_MARKERS = {
    "node": (
        "node_modules/.gaia-installed-",
        ("pnpm-lock.yaml", "pnpm-workspace.yaml", ".npmrc", "package.json"),
    ),
    "python": (
        ".venv/.gaia-synced-",
        (
            "uv.lock",
            "pyproject.toml",
            "apps/api/pyproject.toml",
            "libs/pyproject.toml",
            ".python-version",
        ),
    ),
}
DEP_KEY_CHARS = 16


def dep_marker_key(paths: tuple[str, ...]) -> str:
    """Missing optional inputs hash as a named placeholder, so adding one changes the key."""
    digest = hashlib.sha256()
    for name in paths:
        path = Path(name)
        digest.update(path.read_bytes() if path.is_file() else f"<absent:{name}>".encode())
    return digest.hexdigest()[:DEP_KEY_CHARS]


def cmd_dep_marker(args: list[str]) -> int:
    if not args or args[0] not in DEP_MARKERS:
        log(f"runner.py dep-marker: unknown kind '{args[0] if args else ''}' (node|python)")
        return 2
    prefix, inputs = DEP_MARKERS[args[0]]
    print(prefix + dep_marker_key(inputs))
    return 0


def cmd_heal_venv(args: list[str]) -> int:
    """Remove a venv uv cannot use or will not repair, so the next uv command builds it fresh.

    A dangling bin/python makes uv refuse the dir outright; a missing pyvenv.cfg
    passes uv sync --check while every import fails, and plain uv sync does not
    repair it.
    """
    if not args:
        log("usage: runner.py heal-venv <dir>")
        return 2
    venv = Path(args[0])
    if not venv.exists():
        return 0
    has_python = os.access(venv / "bin" / "python", os.X_OK)
    if has_python and (venv / "pyvenv.cfg").is_file():
        return 0
    missing = "pyvenv.cfg" if has_python else "runnable interpreter"
    ok(f"::warning::runner.py heal-venv: {venv} has no {missing} — removing it so uv recreates it")
    if venv.is_symlink():
        venv.unlink()
    else:
        shutil.rmtree(venv)
    return 0


# ── with-slots ────────────────────────────────────────────────────────────

# lib/cpu-slots.sh is the one governor pytest.sh and mutation.py also use, so
# these are the same tokens. exec: the bash holding the grant IS this process,
# so its EXIT trap releases on cancel and the dead-pid reaper sees its pid.

WITH_SLOTS_SH = (
    'set -euo pipefail; source "$1"; source "$2"; n="$3"; shift 3; '
    'cpu_slots_acquire "$n"; rc=0; "$@" || rc=$?; cpu_slots_release "$n"; exit "$rc"'
)


def cmd_with_slots(args: list[str]) -> int:
    if not args:
        log("usage: runner.py with-slots N -- <cmd...>")
        return 2
    tokens, command = args[0], args[1:]
    if command[:1] == ["--"]:
        command = command[1:]
    if not command:
        log("runner.py with-slots: no command after N")
        return 2
    return os.execvp(
        "bash",
        [
            "bash",
            "-c",
            WITH_SLOTS_SH,
            "with-slots",
            str(LOG_SH),
            str(CPU_SLOTS_SH),
            tokens,
            *command,
        ],
    )


# ── spawn / join ──────────────────────────────────────────────────────────

# A job's steps run one at a time, so a check that runs beside the others starts
# in one step and reports in a later one. Its output, exit code and step summary
# land under $RUNNER_TEMP/bg; join replays them so each check keeps its own log,
# outcome and status. The rc file is written by rename, so join never reads half.

SPAWN_SH = (
    'rc=0; "$@" || rc=$?; printf "%s\\n" "$rc" > "$GAIA_SPAWN_RC.tmp"; '
    'mv -f "$GAIA_SPAWN_RC.tmp" "$GAIA_SPAWN_RC"'
)
SPAWN_NAME = re.compile(r"[a-z0-9][a-z0-9-]*")
JOIN_POLL_SECS = 1.0
FAILURE_TAIL_LINES = 40


@dataclass(frozen=True)
class Background:
    name: str
    root: Path

    @classmethod
    def named(cls, name: str) -> Background:
        temp = os.environ.get("RUNNER_TEMP")
        if not temp:
            raise Die("spawn/join: RUNNER_TEMP is not set")
        if not SPAWN_NAME.fullmatch(name):
            raise Die(f"spawn/join: {name!r} is not a check name (lowercase, digits, dashes)")
        root = Path(temp, "bg")
        root.mkdir(parents=True, exist_ok=True)
        return cls(name, root)

    def path(self, ext: str) -> Path:
        return self.root / f"{self.name}.{ext}"


def cmd_spawn(args: list[str]) -> int:
    if len(args) < 3 or args[1] != "--":
        log("usage: runner.py spawn NAME -- <cmd...>")
        return 2
    bg = Background.named(args[0])
    if bg.path("pid").exists():
        raise Die(f"spawn: {bg.name} was already started in this job")
    env = {
        **os.environ,
        "GAIA_SPAWN_RC": str(bg.path("rc")),
        "GITHUB_STEP_SUMMARY": str(bg.path("summary")),
    }
    with bg.path("log").open("wb") as out:
        child = subprocess.Popen(
            ["bash", "-c", SPAWN_SH, "spawn", *args[2:]],
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=subprocess.STDOUT,
            env=env,
            start_new_session=True,
        )
    bg.path("pid").write_text(f"{child.pid} {time.time()}\n")
    ok(
        f"{bg.name}: running in the background (pid {child.pid}); `runner.py join {bg.name}` reports it"
    )
    return 0


def _wait_for_rc(bg: Background) -> tuple[int, float]:
    """Block until the spawned check records its exit code; fail loud if it died first."""
    pid_text = bg.path("pid")
    if not pid_text.exists():
        raise Die(f"join: {bg.name} was never spawned in this job")
    pid, started = pid_text.read_text().split()
    rc_file = bg.path("rc")
    while not rc_file.exists():
        if not _pid_alive(int(pid)) and not rc_file.exists():
            raise Die(f"join: {bg.name} (pid {pid}) exited without recording an exit code")
        time.sleep(JOIN_POLL_SECS)
    return int(rc_file.read_text()), rc_file.stat().st_mtime - float(started)


def cmd_join(args: list[str]) -> int:
    if len(args) != 1:
        log("usage: runner.py join NAME")
        return 2
    bg = Background.named(args[0])
    rc, elapsed = _wait_for_rc(bg)
    log_text = bg.path("log").read_text(errors="replace")
    print(f"::group::{bg.name} — log ({elapsed:.0f}s, exit {rc})", flush=True)
    sys.stdout.write(log_text if log_text.endswith("\n") or not log_text else log_text + "\n")
    print("::endgroup::", flush=True)
    summary = bg.path("summary")
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary and summary.exists():
        with open(step_summary, "a") as out:
            out.write(summary.read_text())
    if rc != 0:
        tail = log_text.splitlines()[-FAILURE_TAIL_LINES:]
        print("\n".join(tail), flush=True)
        print(
            f"::error title={bg.name}::{bg.name} failed (exit {rc}, {elapsed:.0f}s); "
            "the full log is the group above",
            flush=True,
        )
    return rc


# ── health ────────────────────────────────────────────────────────────────

# A queued lane means an oversubscribed BOX or a busy GitHub POOL — opposite
# fixes, so both are printed. Pool dir and size are read from cpu-slots.sh.

POOL_FACTS_SH = (
    'source "$1"; source "$2"; printf "%s\\n%s\\n" "$(_cpu_slots_dir 2>/dev/null || true)" '
    '"$(_cpu_slots_total)"'
)


def _pool_facts() -> tuple[str, int]:
    proc = subprocess.run(
        ["bash", "-c", POOL_FACTS_SH, "health", str(LOG_SH), str(CPU_SLOTS_SH)],
        capture_output=True,
        text=True,
        check=True,
    )
    directory, total = (proc.stdout.splitlines() + ["", "0"])[:2]
    return directory, int(total or 0)


def _pool_holders(directory: str) -> list[Json]:
    """Every grant in the pool, read outside the lock so a diagnostic never blocks a lane."""
    holders = Path(directory, "holders") if directory else None
    if holders is None or not holders.is_dir():
        return []
    now = time.time()
    found: list[Json] = []
    for path in sorted(holders.iterdir()):
        pid = path.name.split(".", 1)[0]
        try:
            tokens = int(path.read_text().strip())
            age = int(now - path.stat().st_mtime)
        except (OSError, ValueError):
            continue  # reaped between the listing and the read
        alive = pid.isdigit() and _pid_alive(int(pid))
        found.append({"pid": pid, "tokens": tokens, "alive": alive, "age_s": age})
    return found


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _process_counts() -> dict[str, int]:
    proc = subprocess.run(["ps", "-eo", "args="], capture_output=True, text=True, check=True)
    lines = [line for line in proc.stdout.splitlines() if "ps -eo args=" not in line]
    return {
        "mutmut": sum("mutmut" in line for line in lines),
        "pytest": sum("pytest" in line for line in lines),
        "runner_listeners": sum("Runner.Listener" in line for line in lines),
    }


def _listeners() -> dict[str, int | None]:
    label = os.environ.get("RUNNER_LABEL") or DEFAULT_HOME_LABEL
    try:
        pool = read_pool(GitHub.from_env(), repository(), label)
    except GitHubError as err:
        log(f"health: listener probe failed ({err}) — reporting the pool as unknown")
        pool = None
    if pool is None:
        return dict.fromkeys(("online", "busy", "idle", "registered"))
    return {
        "online": pool.online,
        "busy": pool.online - pool.idle,
        "idle": pool.idle,
        "registered": pool.total,
    }


def cmd_health(_args: list[str]) -> int:
    directory, total = _pool_facts()
    holders = _pool_holders(directory)
    held = sum(int(str(h["tokens"])) for h in holders if h["alive"])
    counts = _process_counts()
    load1, load5, load15 = os.getloadavg()
    report = {
        # Off the box this whole report is about a machine running no CI.
        "is_runner_host": counts["runner_listeners"] > 0
        or os.environ.get("RUNNER_NAME", "").startswith(BOX_RUNNER_NAME_PREFIX),
        "listeners": _listeners(),
        "loadavg": {"1m": round(load1, 2), "5m": round(load5, 2), "15m": round(load15, 2)},
        "threads": os.cpu_count() or 0,
        "cpu_slots": {
            "dir": directory or None,
            "total": total,
            "held": held,
            "available": max(total - held, 0),
            "holders": holders,
        },
        "processes": counts,
    }
    print(json.dumps(report, indent=2))
    return 0


# ── dispatch ──────────────────────────────────────────────────────────────

COMMANDS: dict[str, Callable[[list[str]], int]] = {
    "select": cmd_select,
    "watchdog": cmd_watchdog,
    "requeue-stranded": cmd_requeue_stranded,
    "cancel-superseded": cmd_cancel_superseded,
    "rescope": cmd_rescope,
    "prime-archive": cmd_prime_archive,
    "parallel": cmd_parallel,
    "dep-marker": cmd_dep_marker,
    "heal-venv": cmd_heal_venv,
    "with-slots": cmd_with_slots,
    "spawn": cmd_spawn,
    "join": cmd_join,
    "health": cmd_health,
}


def main(argv: list[str]) -> int:
    sub = argv[0] if argv else ""
    command = COMMANDS.get(sub)
    if command is None:
        log(f"runner.py: unknown subcommand '{sub}'")
        log(__doc__ or "")
        return 2
    try:
        return command(argv[1:])
    except (Die, GitHubError) as err:
        print(f"::error::{err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
