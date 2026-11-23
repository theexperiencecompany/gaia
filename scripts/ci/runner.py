#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# ///
"""runner.py — everything about WHERE and HOW HARD a CI job runs.

Subcommands:
  select              Place this run by the live ci.yml runs ahead of it: the
                      first stays GitHub-hosted, later ones move their test
                      slices to free box / M4 slots, Blacksmith only once
                      GitHub is saturated and no slot is free. Writes general /
                      unit / services (runs-on JSON arrays) and is_self_hosted
                      to $GITHUB_OUTPUT (stdout when unset).
  watchdog            Re-dispatch or hand over this run once a self-hosted job
                      has stayed `queued` past the limit on a machine with no
                      live listener — one that died after `select` decided.
  requeue-stranded    Force-cancel and fully re-run any ci.yml run whose lanes are
                      stuck queued on a self-hosted label with no live listener
                      and no live watchdog (scheduled: ci-requeue.yml).
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
  run-job JOB         Run JOB's checks detect selected (nx tasks whose target's
                      metadata.ci.job is JOB, minus the reused) through nx,
                      under this runner's CPU budget, and write each task's
                      result for `verdict.py post-statuses`.
  health              Print, as JSON, what the box is actually doing: the home
                      listener pool, load average, thread count, who holds CPU
                      slots, and how many mutmut/pytest processes are running.
                      Read-only; never fails.

Env contract:
  every API call      lib/github.py's (token, base URL, timeout, retries).
  select              GITHUB_REPOSITORY, GITHUB_RUN_ID, GITHUB_EVENT_NAME,
                      GITHUB_WORKFLOW_REF, GITHUB_HEAD_REF or GITHUB_REF_NAME,
                      RUNNER_LABEL (the box, default gaia-home), M4_LABEL
                      (empty: no M4), FALLBACK_RUNNER (default
                      [HOSTED_LINUX_IMAGE]), FORCE_HOME, FORCE_GITHUB,
                      PR_HEAD_REPO, PR_AUTHOR_ASSOCIATION, GITHUB_ACTOR,
                      BLACKSMITH_LABEL (empty: never); writes $GITHUB_OUTPUT
                      and $GITHUB_STEP_SUMMARY.
  watchdog            GITHUB_REPOSITORY, GITHUB_RUN_ID, WATCHDOG_JOB_NAME
                      (required), QUEUE_LIMIT_SECS (480), POLL_SECS (30),
                      GITHUB_EVENT_NAME, GITHUB_WORKFLOW_REF, GITHUB_HEAD_REF
                      or GITHUB_REF_NAME, DEFAULT_BRANCH (merge_group: where
                      ci-requeue.yml runs).
  requeue-stranded    GITHUB_REPOSITORY,
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
  run-job             JOB_TASKS (detect's job_tasks), REUSED (detect's reused),
                      RESULTS_FILE (where the task results land; required).
  health              GITHUB_REPOSITORY, RUNNER_LABEL (gaia-home); reads the
                      cpu-slots pool dir, never takes from it.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import datetime
from enum import StrEnum
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

from lib import nx_affected, runner_host
from lib.github import GitHub, GitHubError, Json, field_of, records, text_of

HERE = Path(__file__).resolve().parent
LOG_SH = HERE / "lib" / "log.sh"
CPU_SLOTS_SH = HERE / "lib" / "cpu-slots.sh"

DEFAULT_REPO = "theexperiencecompany/gaia"
DEFAULT_HOME_LABEL = "gaia-home"
# The GitHub-hosted Linux image, by release: ubuntu-latest moves under us (it
# rolled to 26.04 job by job, run 45079269367). check_tool_pins.py holds every
# literal runs-on in .github to this release.
HOSTED_LINUX_IMAGE = "ubuntu-24.04"
DEFAULT_FALLBACK = json.dumps([HOSTED_LINUX_IMAGE])
TEST_SLICES_JSON = HERE / "lib" / "test-slices.json"
REQUEUE_WORKFLOW = "ci-requeue.yml"
# The one workflow that routes jobs to self-hosted labels.
CI_WORKFLOW = "ci.yml"
SELF_HOSTED = "self-hosted"


ACTIVE_RUN_STATUSES = frozenset({"queued", "pending", "waiting", "in_progress"})
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
    # Online or busy: a busy listener is running a job whatever its status reads.
    alive: int

    def describe(self) -> str:
        return f"{self.idle} idle / {self.online} online / {self.total} registered"


def _runner_labels(runner: Json) -> list[str]:
    return [field_of(label, "name", str) for label in records(runner, "labels")]


def read_runners(gh: GitHub, repo: str) -> list[Json]:
    return gh.collect(f"repos/{repo}/actions/runners?per_page=100", "runners")


def pool_of(runners: list[Json], label: str) -> Pool | None:
    """Count the instances carrying the label; None when no instance is registered with it."""
    matching = [r for r in runners if label in _runner_labels(r)]
    if not matching:
        return None
    online = [r for r in matching if field_of(r, "status", str) == "online"]
    idle = [r for r in online if field_of(r, "busy", bool) is False]
    alive = [r for r in matching if r in online or field_of(r, "busy", bool)]
    return Pool(label, len(online), len(idle), len(matching), len(alive))


class HomeState(StrEnum):
    ONLINE = "online"
    OFFLINE = "offline"
    UNKNOWN = "unknown"


def home_state(gh: GitHub, repo: str, label: str) -> HomeState:
    """Report whether any instance of the label is online; UNKNOWN is never a reason to act."""
    try:
        pool = pool_of(read_runners(gh, repo), label)
    except GitHubError as err:
        log(f"runners probe failed ({err}) — cannot say whether '{label}' is alive")
        return HomeState.UNKNOWN
    alive = pool.alive if pool else 0
    log(f"{alive} runner(s) online or busy with label '{label}'")
    return HomeState.ONLINE if alive else HomeState.OFFLINE


# ── select ────────────────────────────────────────────────────────────────


# A run is placed by the runs ahead of it, never by GitHub's queue depth: runs
# that start together each read that queue as empty (0-2 of a threshold of 5 in
# a 4-run burst), so none overflowed, while every run exists the moment its push
# lands. Each run computes the same placement for the runs ahead of it, so runs
# deciding at once get distinct answers without talking to each other.


def _job_labels(job: Json) -> list[str]:
    labels = job.get("labels") or []
    if not isinstance(labels, list) or not all(isinstance(x, str) for x in labels):
        raise GitHubError("job 'labels' is not a list of strings")
    return [str(x) for x in labels]


class JobPool(StrEnum):
    """Where a job may run: `general` stays GitHub-hosted, the slices can move."""

    GENERAL = "general"
    UNIT = "unit"
    SERVICES = "services"


# Services first: the box is their only machine, while unit slices can take the M4.
PLACEMENT_ORDER = (JobPool.SERVICES, JobPool.UNIT)
# Runs ahead that still leave a run on GitHub-hosted: a lone run never moves.
HOSTED_RUNS = 1
# Runs ahead at which GitHub's 20 hosted slots are taken (4 runs at once took
# 21-32 min each, 12-14 alone): the precondition for paying for Blacksmith.
SATURATED_RUNS = 2
# Slices the 16-thread box runs at hosted speed: at 10 jobs its load hit 63-67.
BOX_SLOTS = 4
# Jobs the M4 VM's 20 GiB holds; three at once swapped.
M4_SLOTS = 2
# A run whose detect job completed has created every slice job it will run.
DETECT_JOB = "detect"
# Events whose newer run on a branch cancels the older one (cancel-superseded).
SUPERSEDING_EVENTS = frozenset({"pull_request", "push"})
JOB_READ_WORKERS = 8
# Sorts after every ISO-8601 stamp: a run missing from the listing decides last.
NOT_LISTED_YET = "~"
# A run still `queued` this long after creation never started (select-runner starts
# in seconds); three such runs from 11 Nov were still listed on 23 Nov with no job.
NEVER_STARTED_SECS = 20 * 60


def slice_demand(event: str) -> Counter[JobPool]:
    """Count the slices of the event's tier in each pool: a PR runs the fast tier."""
    slices = records(json.loads(TEST_SLICES_JSON.read_text()), "slices")
    fast_only = event == "pull_request"
    return Counter(
        JobPool(field_of(s, "pool", str))
        for s in slices
        if not fast_only or field_of(s, "tier", str) == "fast"
    )


@dataclass(frozen=True)
class Machine:
    label: str
    slots: int
    pools: frozenset[JobPool]
    takes_merge_groups: bool
    # Registered listeners past which the machine is refused; None when its CPU is governed.
    max_listeners: int | None

    def serves(self, run: Run, pool: JobPool) -> bool:
        return pool in self.pools and (run.event != "merge_group" or self.takes_merge_groups)


@dataclass(frozen=True)
class Run:
    id: int
    event: str
    branch: str
    started: str
    trusted: bool

    @classmethod
    def parse(cls, doc: Json, repo: str) -> Run:
        head = doc.get("head_repository")
        actor = doc.get("triggering_actor") or doc.get("actor")
        login = field_of(actor, "login", str) if isinstance(actor, dict) else ""
        return cls(
            id=field_of(doc, "id", int),
            event=field_of(doc, "event", str),
            branch=text_of(doc, "head_branch"),
            # A re-run restarts run_started_at, so it decides behind the runs already deciding.
            started=text_of(doc, "run_started_at") or text_of(doc, "created_at"),
            trusted=isinstance(head, dict)
            and field_of(head, "full_name", str) == repo
            and not login.endswith("[bot]"),
        )

    def order(self) -> tuple[str, int]:
        return self.started, self.id

    @property
    def movable(self) -> bool:
        """Whether its slices may leave GitHub-hosted at all (a master push deploys from hosted)."""
        return self.trusted and self.event != "push"


@dataclass(frozen=True)
class Runs:
    """The live runs in decision order, and the superseded ones still being cancelled."""

    live: list[Run]
    # Not ahead of anyone, but their self-hosted jobs run on while they are
    # force-cancelled (and a cancelled pytest step wedges its listener for 5 min).
    superseded: list[Run]


def active_runs(gh: GitHub, repo: str, workflow: str, me: Run) -> Runs:
    found = {me.id: me}
    never_started = int(time.time()) - NEVER_STARTED_SECS
    for status in ("queued", "in_progress"):
        path = f"repos/{repo}/actions/workflows/{workflow}/runs?status={status}&per_page=100"
        for doc in records(gh.get(path), "workflow_runs"):
            run = Run.parse(doc, repo)
            # run_started_at, not created_at: a re-run keeps its created_at.
            if status == "queued" and epoch(run.started) < never_started:
                continue
            found[run.id] = run
    ordered = sorted(found.values(), key=Run.order)
    newest = {(r.event, r.branch): r for r in ordered if r.event in SUPERSEDING_EVENTS}

    def is_live(r: Run) -> bool:
        return (
            r.id == me.id or r.event not in SUPERSEDING_EVENTS or newest[(r.event, r.branch)] is r
        )

    return Runs([r for r in ordered if is_live(r)], [r for r in ordered if not is_live(r)])


@dataclass(frozen=True)
class Held:
    """What a run ahead really holds, read from its jobs."""

    # False while detect runs: its slice jobs do not exist yet.
    settled: bool
    slots: Counter[str]
    # Labels with a job in progress: their listeners are alive whatever the runners API says.
    running: frozenset[str]


def read_held(gh: GitHub, repo: str, run_id: int, labels: frozenset[str]) -> Held:
    listed = gh.collect(
        f"repos/{repo}/actions/runs/{run_id}/jobs?filter=latest&per_page=100", "jobs"
    )
    settled = any(
        field_of(j, "name", str) == DETECT_JOB and field_of(j, "status", str) == "completed"
        for j in listed
    )
    slots: Counter[str] = Counter()
    running: set[str] = set()
    for job in listed:
        status = field_of(job, "status", str)
        for label in labels.intersection(_job_labels(job)):
            if status != "completed":
                slots[label] += 1
            if status == "in_progress":
                running.add(label)
    return Held(settled, slots, frozenset(running))


def plan_run(
    run: Run, ahead: int, free: dict[str, int], machines: list[Machine]
) -> dict[JobPool, Machine | None]:
    """Place a run's movable slice pools, taking their slots from free; empty when it stays hosted."""
    if not run.movable or ahead < HOSTED_RUNS:
        return {}
    demand = slice_demand(run.event)
    placed: dict[JobPool, Machine | None] = {}
    for pool in (p for p in PLACEMENT_ORDER if demand[p]):
        machine = next(
            (m for m in machines if m.serves(run, pool) and free[m.label] >= demand[pool]), None
        )
        if machine is not None:
            free[machine.label] -= demand[pool]
        placed[pool] = machine
    return placed


@dataclass(frozen=True)
class Choice:
    runs_on: tuple[str, ...]
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
    """One select invocation: this run's place among the live runs decides its slices' runner."""

    gh: GitHub
    repo: str
    fallback: tuple[str, ...]
    machines: list[Machine]
    blacksmith: str
    me: Run

    def hosted(self, reason: str, note: str) -> dict[JobPool, Choice]:
        return dict.fromkeys(JobPool, Choice(self.fallback, reason, note))

    def route(self) -> dict[JobPool, Choice]:
        try:
            runs = active_runs(self.gh, self.repo, workflow_file(), self.me)
            ahead = runs.live[: [r.id for r in runs.live].index(self.me.id)]
            if len(ahead) < HOSTED_RUNS or not self.me.movable:
                return self.hosted("hosted-first", f"{len(ahead)} run(s) ahead")
            free = self.free_slots(ahead, runs.superseded)
        except GitHubError as err:
            warn(f"run or job listing failed ({err}) — every pool stays on GitHub-hosted")
            return self.hosted("runs-unknown", "run or job listing unreadable")
        log(f"[select-runner] runs ahead: {[r.id for r in ahead]}; free slots: {free}")
        placed = plan_run(self.me, len(ahead), free, self.machines)
        choices = self.hosted("hosted-general", "general jobs stay on GitHub-hosted")
        for pool, machine in placed.items():
            choices[pool] = self.choose(pool, machine, len(ahead))
        return choices

    def choose(self, pool: JobPool, machine: Machine | None, ahead: int) -> Choice:
        note = f"{ahead} run(s) ahead"
        if machine is not None:
            return Choice((SELF_HOSTED, machine.label), "self-hosted", note)
        if ahead < SATURATED_RUNS or not self.blacksmith:
            return Choice(self.fallback, "no-free-slot", f"{note}; no self-hosted slot free")
        warn(
            f"{pool.value} slices of run {self.me.id} go to Blacksmith (`{self.blacksmith}`), "
            f"which is paid per job-minute: {ahead} runs are ahead on GitHub-hosted and "
            "neither the box nor the M4 has a free slot."
        )
        return Choice((self.blacksmith,), "blacksmith-last-resort", note)

    def free_slots(self, ahead: list[Run], superseded: list[Run]) -> dict[str, int]:
        """Return each machine's free slots once every run ahead, and every run still being cancelled, has taken what it holds."""
        labels = frozenset(m.label for m in self.machines)
        readable = [r for r in [*ahead, *superseded] if r.movable]
        with ThreadPoolExecutor(max_workers=JOB_READ_WORKERS) as pool:
            reads = pool.map(lambda r: read_held(self.gh, self.repo, r.id, labels), readable)
            held = dict(zip((r.id for r in readable), reads, strict=True))
        running = frozenset().union(*(h.running for h in held.values()))
        free = self.capacity(running)
        for run in superseded:
            for label, taken in held[run.id].slots.items() if run.id in held else ():
                free[label] -= taken
        for position, run in enumerate(ahead):
            reading = held.get(run.id)
            if reading is not None and reading.settled:
                for label, taken in reading.slots.items():
                    free[label] -= taken
            else:
                plan_run(run, position, free, self.machines)
        return free

    def capacity(self, running: frozenset[str]) -> dict[str, int]:
        try:
            runners = read_runners(self.gh, self.repo)
        except GitHubError as err:
            warn(
                f"runners API unavailable ({err}) — no self-hosted machine takes this run's slices"
            )
            return {m.label: 0 for m in self.machines}
        capacity = {}
        for machine in self.machines:
            pool = pool_of(runners, machine.label)
            if pool and machine.max_listeners is not None and pool.total > machine.max_listeners:
                warn(
                    f"`{machine.label}` has {pool.total} listeners for {machine.max_listeners} "
                    "slots and nothing on it caps CPU per job — not routing to it until it has "
                    f"at most {machine.max_listeners}"
                )
                capacity[machine.label] = 0
                continue
            alive = pool.alive if pool else 0
            if not alive and machine.label in running:
                log(
                    f"[select-runner] the runners API lists no live `{machine.label}` listener, "
                    "but a run ahead has a job in progress on it: trusting the job"
                )
                alive = machine.slots
            capacity[machine.label] = min(machine.slots, alive)
        return capacity


def machines_from_env(box: str) -> list[Machine]:
    """List the self-hosted machines in the order unit slices try them: the M4 first, when on."""
    # The box's cpu-slots governor and static xdist shares hold its 10 listeners in check.
    found = [Machine(box, BOX_SLOTS, frozenset({JobPool.UNIT, JobPool.SERVICES}), True, None)]
    if m4 := os.environ.get("M4_LABEL", ""):
        # No governor there, and pytest sizes its workers by the whole VM.
        found.insert(0, Machine(m4, M4_SLOTS, frozenset({JobPool.UNIT}), False, M4_SLOTS))
    return found


def forced_home(gh: GitHub, repo: str, label: str) -> Choice:
    try:
        pool = pool_of(read_runners(gh, repo), label)
    except GitHubError as err:
        raise Die(f"HOME runner forced but the runners API probe failed ({err})") from err
    if pool is None:
        raise Die(f"HOME runner forced but no runner with label {label} is registered")
    if not pool.online:
        raise Die(f"HOME runner forced but `{label}` is offline ({pool.describe()})")
    return Choice((SELF_HOSTED, label), "forced-home", f"`{label}`: {pool.describe()}")


def route() -> dict[JobPool, Choice]:
    repo = repository()
    fallback = _fallback_runner()
    gate = trust_gate(repo)
    gh = GitHub.from_env()
    if gate is None and not gh.token:
        gate = ("no-token", "no API token available (local run)")
    if gate is not None:
        return dict.fromkeys(JobPool, Choice(fallback, *gate))
    box = os.environ.get("RUNNER_LABEL") or DEFAULT_HOME_LABEL
    if os.environ.get("FORCE_HOME") == "true":
        return dict.fromkeys(JobPool, forced_home(gh, repo, box))
    event = env_required("GITHUB_EVENT_NAME")
    branch = os.environ.get("GITHUB_HEAD_REF") or os.environ.get("GITHUB_REF_NAME", "")
    me = Run(env_int("GITHUB_RUN_ID", 0), event, branch, NOT_LISTED_YET, trusted=True)
    router = Router(
        gh=gh,
        repo=repo,
        fallback=fallback,
        machines=machines_from_env(box),
        blacksmith=os.environ.get("BLACKSMITH_LABEL", ""),
        me=me,
    )
    return router.route()


def cmd_select(_args: list[str]) -> int:
    choices = route()
    self_hosted = any(choice.is_self_hosted for choice in choices.values())
    lines = [
        f"is_self_hosted={str(self_hosted).lower()}",
        *(f"{pool.value}={choice.runs_on_json()}" for pool, choice in choices.items()),
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
        "| pool | runs-on | reason | why |",
        "| --- | --- | --- | --- |",
        *(
            f"| {pool.value} | `{c.runs_on_json()}` | {c.reason} | {c.note} |"
            for pool, c in choices.items()
        ),
    ]
    log("[select-runner] " + "\n".join(summary))
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY", "")
    if summary_file and Path(summary_file).is_file():
        with open(summary_file, "a", encoding="utf-8") as handle:
            handle.write("\n".join(summary) + "\n")
    return 0


# ── watchdog ──────────────────────────────────────────────────────────────

# A machine that dies after select leaves its jobs queued for up to 24 h. A
# busy machine and an unreadable runners probe both mean keep waiting.

# How long a self-hosted job may sit queued before its machine is judged; the
# watchdog and requeue-stranded both read it, and ci.yml's watchdog cap covers it.
QUEUE_LIMIT_SECS = 480
WATCHDOG_POLL_SECS = 30
# The re-dispatch and cancel calls after the last poll, with room to spare.
WATCHDOG_MARGIN_SECS = 60
WATCHDOG_JOB = "watchdog"


@dataclass(frozen=True)
class Job:
    name: str
    status: str
    created: int
    labels: tuple[str, ...]

    @classmethod
    def parse(cls, doc: Json) -> Job:
        return cls(
            name=field_of(doc, "name", str),
            status=field_of(doc, "status", str),
            created=epoch(text_of(doc, "created_at")),
            labels=tuple(_job_labels(doc)),
        )

    @property
    def machine(self) -> str:
        """The self-hosted label this job waits for; empty for a GitHub-hosted or Blacksmith job."""
        if SELF_HOSTED not in self.labels:
            return ""
        return next((label for label in self.labels if label != SELF_HOSTED), SELF_HOSTED)


def _stalled_job(jobs: list[Job], limit: int) -> Job | None:
    # A job is created when its needs resolve, so its own creation is its eligibility.
    # Other jobs' progress says nothing: GitHub-hosted lanes run on beside a dead label.
    now = int(time.time())
    stalled = None
    for job in (j for j in jobs if j.status == "queued" and j.machine):
        age = now - job.created
        ok(f"watchdog: '{job.name}' eligible for {age}s (limit {limit}s)")
        if age > limit:
            stalled = job
    return stalled


def _machine_state(gh: GitHub, label: str, jobs: list[Job]) -> HomeState:
    """Read a label's liveness; an "offline" listing loses to a job of this run in progress on it."""
    state = home_state(gh, repository(), label)
    running = next((j for j in jobs if j.status == "in_progress" and j.machine == label), None)
    if state is HomeState.OFFLINE and running is not None:
        warn(
            f"the runners API lists no live '{label}' listener, but '{running.name}' is "
            "in progress on it — trusting the job over the listing"
        )
        return HomeState.ONLINE
    return state


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


def _watch_once(gh: GitHub, run: str, me: str, limit: int) -> int | None:
    """One poll; an exit code when the watch is over, None to keep watching."""
    status = field_of(gh.get(run), "status", str)
    if status not in ACTIVE_RUN_STATUSES:
        ok(f"watchdog: run is {status} — nothing left to watch")
        return 0
    jobs = [Job.parse(j) for j in gh.collect(f"{run}/jobs?per_page=100", "jobs")]
    jobs = [j for j in jobs if j.name != me]
    if not jobs:
        # Lanes whose `needs:` have not resolved have no record yet.
        ok(f"watchdog: no lanes created yet (run {status}) — waiting")
        return None
    if not any(j.status == "queued" and j.machine for j in jobs):
        # It starts after detect, which is when the slices select moved off GitHub are created.
        ok("watchdog: every self-hosted lane was picked up")
        return 0
    stalled = _stalled_job(jobs, limit)
    if stalled is None:
        return None
    match _machine_state(gh, stalled.machine, jobs):
        case HomeState.ONLINE:
            warn(
                f"'{stalled.name}' has been queued for over {limit}s, but instances labelled "
                f"'{stalled.machine}' are online — the machine is busy, not dead. Not cancelling."
            )
        case HomeState.UNKNOWN:
            warn(
                f"'{stalled.name}' has been queued for over {limit}s and the runners API could "
                "not be probed — not cancelling on an unknown."
            )
        case HomeState.OFFLINE:
            return _redispatch_or_cancel(gh, run, stalled.name, limit, stalled.machine)
    return None


def cmd_watchdog(_args: list[str]) -> int:
    limit = env_int("QUEUE_LIMIT_SECS", QUEUE_LIMIT_SECS)
    poll = env_int("POLL_SECS", WATCHDOG_POLL_SECS)
    me = env_required("WATCHDOG_JOB_NAME")
    run = f"repos/{env_required('GITHUB_REPOSITORY')}/actions/runs/{env_required('GITHUB_RUN_ID')}"
    gh = GitHub.from_env()
    while (code := _watch_once(gh, run, me, limit)) is None:
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


def _stranded_job(gh: GitHub, repo: str, run_id: int, limit: int, *, swept: bool) -> Job | None:
    """Return a self-hosted job of the run queued past the limit; a sweep leaves a live watchdog's run to it."""
    now = int(time.time())
    jobs = [
        Job.parse(j)
        for j in gh.collect(f"repos/{repo}/actions/runs/{run_id}/jobs?per_page=100", "jobs")
    ]
    if swept and any(j.name == WATCHDOG_JOB and j.status != "completed" for j in jobs):
        return None
    stranded = None
    for job in jobs:
        if job.status == "queued" and job.machine and now - job.created > limit:
            stranded = job
    return stranded


def _requeue_candidates(gh: GitHub, repo: str) -> list[int]:
    """Return the run a watchdog handed over, else every in-flight ci.yml run (only it routes)."""
    if handed_over := os.environ.get("REQUEUE_RUN_ID"):
        return [int(handed_over)]
    return [
        field_of(run, "id", int)
        for status in ("queued", "in_progress")
        for run in gh.collect(
            f"repos/{repo}/actions/workflows/{CI_WORKFLOW}/runs?per_page=100&status={status}",
            "workflow_runs",
        )
    ]


def cmd_requeue_stranded(_args: list[str]) -> int:
    limit = env_int("QUEUE_LIMIT_SECS", QUEUE_LIMIT_SECS)
    wait = env_int("CANCEL_WAIT_SECS", 180)
    poll = env_int("POLL_SECS", 10)
    repo = env_required("GITHUB_REPOSITORY")
    gh = GitHub.from_env()
    swept = not os.environ.get("REQUEUE_RUN_ID")
    states: dict[str, HomeState] = {}
    failed = 0
    for run_id in _requeue_candidates(gh, repo):
        stranded = _stranded_job(gh, repo, run_id, limit, swept=swept)
        if stranded is None:
            continue
        label = stranded.machine
        if label not in states:
            states[label] = home_state(gh, repo, label)
        match states[label]:
            case HomeState.ONLINE:
                ok(f"requeue-stranded: run {run_id}: '{label}' is online — busy, not stranded")
                continue
            case HomeState.UNKNOWN:
                # Touch nothing, but fail: a sweep that cannot see the runners has not done its job.
                warn(
                    f"requeue-stranded: run {run_id}: the runners API could not be probed — "
                    "not touching it on an unknown"
                )
                failed = 1
                continue
        ok(
            f"requeue-stranded: run {run_id}: '{stranded.name}' queued on '{label}' past {limit}s "
            f"with no '{label}' runner online — force-cancelling to re-run in full"
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


# A production deploy is never cancelled mid-flight: a cancelled wrangler deploy
# leaves R2's prerendered cache half-filled, a cancelled stack deploy a half-rolled
# Swarm. A deploy phase's jobs exist only once the gate let it start, so any of
# them not yet completed means it has started. The newer run deploys after it,
# queued behind the deploy jobs' own concurrency groups.
DEPLOY_JOB_PREFIXES = ("deploy-web", "trigger-build")


def _deploying(gh: GitHub, repo: str, run_id: int) -> bool:
    jobs = gh.collect(f"repos/{repo}/actions/runs/{run_id}/jobs?filter=latest&per_page=100", "jobs")
    return any(
        field_of(job, "name", str).startswith(DEPLOY_JOB_PREFIXES)
        and field_of(job, "status", str) != "completed"
        for job in jobs
    )


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
        if os.environ.get("GITHUB_EVENT_NAME") == "push" and _deploying(gh, repo, old):
            ok(f"run {old} is deploying to production: left to finish, this run deploys after it")
            continue
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


# ── run-job ───────────────────────────────────────────────────────────────
# A grouped job's checks are nx tasks (nx_affected.run). Each check's status is
# posted the moment its last task finishes, so a red check shows while the slow
# ones still run; post-statuses at the job's end posts the rest and the verdict.


def cmd_run_job(args: list[str]) -> int:
    if len(args) != 1:
        raise Die("usage: runner.py run-job <job>")
    job = args[0]
    planned: list[str] = json.loads(os.environ.get("JOB_TASKS") or "{}").get(job, [])
    reused: dict[str, str] = json.loads(os.environ.get("REUSED") or "{}")
    results_file = Path(env_required("RESULTS_FILE"))
    known = nx_affected.checks()
    tasks = [
        task for task in planned if known[task].runner == "nx" and known[task].check not in reused
    ]
    waiting: dict[str, set[str]] = {}
    for task in tasks:
        waiting.setdefault(str(known[task].check), set()).add(task)
    results: dict[str, nx_affected.TaskResult] = {}

    def on_done(task: str, result: nx_affected.TaskResult) -> None:
        results[task] = result
        results_file.write_text(json.dumps(results, indent=2) + "\n")
        check = str(known[task].check)
        passed = result["status"] in nx_affected.PASSED
        if passed:
            print(
                f"::group::{check}: passed ({task})\n{result['output']}\n::endgroup::", flush=True
            )
        else:
            print(
                f"{check}: FAILED ({task}, exit {result['code']})\n{result['output']}", flush=True
            )
        waiting[check].discard(task)
        if not waiting[check]:
            _post_check_status(job, check, results_file)

    parallel = measure_parallelism().nx
    passed = nx_affected.run(tasks, parallel, _cpu_slots, on_done)
    results_file.write_text(json.dumps(results, indent=2) + "\n")
    ok(f"run-job {job}: {len(tasks)} task(s); {len(planned) - len(tasks)} reused or run by a step")
    return 0 if passed else 1


def _cpu_slots(cores: int) -> list[str]:
    """Prefix a command so it holds `cores` host CPU tokens while it runs (a no-op off the box)."""
    return ["bash", "-c", WITH_SLOTS_SH, "with-slots", str(LOG_SH), str(CPU_SLOTS_SH), str(cores)]


def _post_check_status(job: str, check: str, results_file: Path) -> None:
    """Post one finished check's status now; post-statuses at the job's end posts any that did not land."""
    subprocess.run(
        [
            sys.executable, str(HERE / "verdict.py"), "post-statuses", "--job", job,
            "--check", check, "--results", str(results_file),
            "--job-tasks", os.environ.get("JOB_TASKS") or "{}",
            "--reused", os.environ.get("REUSED") or "{}",
            *_post_target(),
        ],
        check=False,
    )  # fmt: skip


def _post_target() -> list[str]:
    if os.environ.get("NO_POST"):
        return ["--no-post"]
    return [
        "--repo", env_required("GITHUB_REPOSITORY"), "--sha", env_required("HEAD_SHA"),
        "--run-id", env_required("GITHUB_RUN_ID"), "--job-id", env_required("JOB_CHECK_RUN_ID"),
    ]  # fmt: skip


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
        pool = pool_of(read_runners(GitHub.from_env(), repository()), label)
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
        "is_runner_host": counts["runner_listeners"] > 0 or runner_host.on_the_box(),
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
    "run-job": cmd_run_job,
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
