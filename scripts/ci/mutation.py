#!/usr/bin/env python3
"""mutation.py — mutation testing: would the suite notice if this code were wrong?

Subcommands:
  matrix                   Emit the changed app modules + their test files as
                           JSON — the input `plan` and `local` fan out from.
                           Fails loudly when changed app code has no test.
  plan                     Emit the lane's GitHub Actions matrix — one shard
                           per changed module, capped at MAX_SHARDS. Writes
                           shards (the labels), shard_defs and count to
                           $GITHUB_OUTPUT.
  shard                    Run every module in $GROUP, in order; the shard's
                           exit code is the last failing module's.
  module <mod> [tests] [ranges]
                           Mutate ONE module with mutmut and require the suite
                           to kill every mutant on the PR's changed lines.
                           This is the engine both `shard` and `local` drive.
  local [modules...]       Run the whole gate on this machine exactly as the
                           lane runs it, sized to the local CPU budget. Logs
                           under verify-logs/mutation/.
  replay <verdict|dir|shard.log> <mutant-id|file.py:LINE>
                           Re-apply ONE survivor's diff to a scratch copy of
                           apps/api and run that module's mapped tests.

Env contract:
  matrix  none directly; delegates the diff to `changes.sh files py`.
  plan    GITHUB_OUTPUT (stdout-only when unset).
  shard   GROUP (required, compact JSON array of {module,testfiles,ranges});
          SHARD_LOG (shard.log), GITHUB_STEP_SUMMARY. Writes <shard>.verdict.json
          beside the log (the replay artifact) and one verdict per module through
          `verdict.py emit` into the directory `verdict.py dir` reports.
  module  MUTMUT_WORKDIR_BASE, MUTMUT_MAX_CHILDREN, MUTMUT_KEEP_WORKDIR,
          MUTATION_VERDICT_DIR (where the module RECORD lands).
  local   MUTATION_JOBS, MUTATION_CPU_BUDGET, MUTMUT_MAX_CHILDREN.
  replay  none.

Every exit path of `module` ends in one `Outcome`, and the record it writes is
the module's verdict: the shard reads those records, never its own log. A
missing record means the module was killed or crashed, and says so.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from enum import StrEnum
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from types import FrameType
from typing import IO
from urllib.parse import urlparse

from lib import mutation_report as report

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
LIB = SCRIPT_DIR / "lib"

# Bounded so the matrix stays clear of GitHub's 256-job limit (a skipped lane
# counts as a pass), and equal to the workflow's max-parallel so every shard
# starts at once. Six, not four: a 110-module diff at 4 shards ran out of clock
# with every finished module clean (run 34476365942) — the shard has to fit.
MAX_SHARDS = 6
POOLS = ("unit", "services")
# The one test tier that needs live Mongo and Redis: `plan` groups by it and
# `shard` re-derives its own pool from it, through `needs_services`.
SERVICES_TIER = "tests/contracts/"

# A shard's per-module cap, enforced from outside the module process.
MODULE_TIMEOUT_SECONDS = 1500
# mutmut's own cap inside a module: ~10x the slowest honest module (1.2 min).
MUTMUT_TIMEOUT_SECONDS = 720
KILLED_BY_CAP = 137
MUTMUT_TIMED_OUT = 124
# Per-mutant pytest timeout; timeout_func_only keeps fixture setup (a 30-40 s
# app build when cold sessions start together) off the test's own budget.
MUTANT_TEST_TIMEOUT = 120
PLUGIN_FENCE = (
    '-m "not composio and not model_onboarding and not schemathesis" --strict-markers '
    "-p no:opik -p no:langsmith_plugin -p no:schemathesis"
)
PLAIN_RUN_ADDOPTS = f"addopts={PLUGIN_FENCE} --timeout=300"
LOCAL_LOG_DIR = Path("verify-logs/mutation")
SHARD_LOG_TAIL_BYTES = 200_000
TMPFS = Path("/dev/shm")
TMPFS_MIN_FREE_BYTES = 1 << 30

# mutmut's statuses: only killed and survived are a verdict, the rest count.
COUNTED_STATUSES = frozenset(
    {
        "killed",
        "survived",
        "suspicious",
        "no tests",
        "not checked",
        "timeout",
        "segfault",
        "skipped",
        "caught by type check",
    }
)
# A chromadb client's Rust core does not survive fork(): SIGTRAP on macOS,
# a deadlock killed at its CPU limit on Linux.
FORK_CRASH_EXIT_CODES = frozenset({-5, -24})
# scripts/test/mutmut_in_test_marker.py leaves one file here per mutant child
# killed inside a test body: a real timeout, never the fork crash.
IN_TEST_DIR = "mutants-killed-in-test"
IN_TEST_DIR_ENV = "MUTMUT_IN_TEST_DIR"
_RESULT_LINE = re.compile(r"^\s+(?P<name>\S+__mutmut_\d+): (?P<status>.+)$")
_TIMED_OUT_TEST = re.compile(r"^(FAILED|ERROR) .*Failed: Timeout \(>", re.MULTILINE)
CLASSIFIER_KINDS = ("EQUIV", "CHANGED", "UNCHANGED", "LOGGING", "LINTED")

# Holds the host CPU tokens for as long as its stdin stays open, through the
# same lib/cpu-slots.sh every other lane on the box coordinates with.
_CPU_SLOT_HOLDER = (
    'source "$1"; source "$2"; cpu_slots_acquire "$3"; echo held; '
    'read -r _ || true; cpu_slots_release "$3"'
)


class Status(StrEnum):
    """A module's outcome, in this lane's own vocabulary (mutation_report.CONTRACT_STATUS)."""

    PASS = "pass"
    SURVIVORS = "survivors"
    GAP = "gap"
    SKIP = "skip"
    TIMED_OUT = "timed_out"
    ERROR = "error"


class RunFailure(StrEnum):
    """Why a non-zero mutmut run ended, as mutmut itself prints it."""

    NO_COVERING_TEST = "could not find any test case for any mutant"
    CLEAN_RUN_FAILED = "Failed to run clean test"
    BAD_TEST_COMMAND = "BadTestExecutionCommandsException"
    IMPORT_TIME_SELF_CALL = "No such file or directory: '<frozen importlib._bootstrap>'"


@dataclass(frozen=True)
class ModuleWork:
    """One module the lane mutates: its mapped tests and the PR's changed line ranges."""

    module: str
    testfiles: tuple[str, ...]
    ranges: str

    @property
    def needs_services(self) -> bool:
        return any(f.startswith(SERVICES_TIER) for f in self.testfiles)

    @classmethod
    def from_matrix(cls, item: dict[str, object]) -> ModuleWork:
        testfiles = item["testfiles"]
        if not isinstance(testfiles, list):
            raise ValueError(f"testfiles of {item['module']} is not a list")
        return cls(
            module=str(item["module"]),
            testfiles=tuple(str(f) for f in testfiles),
            ranges=_compact(item["changed_lines"]),
        )

    @classmethod
    def from_group(cls, item: dict[str, str]) -> ModuleWork:
        testfiles = json.loads(item["testfiles"])
        if not isinstance(testfiles, list) or not all(isinstance(f, str) for f in testfiles):
            raise ValueError(f"testfiles of {item['module']} is not a JSON list of paths")
        return cls(module=item["module"], testfiles=tuple(testfiles), ranges=item["ranges"])

    def to_group(self) -> dict[str, str]:
        return {
            "module": self.module,
            "testfiles": _compact(list(self.testfiles)),
            "ranges": self.ranges,
        }


@dataclass(frozen=True)
class Shard:
    pool: str
    work: tuple[ModuleWork, ...]

    def matrix_entry(self, number: int, total: int) -> dict[str, str]:
        # A lone module names its own check; a packed shard says how many it
        # carries, so nothing looks dropped; a services shard says so.
        label = (
            self.work[0].module
            if len(self.work) == 1
            else f"shard {number}/{total} ({len(self.work)} modules)"
        )
        if self.pool == "services":
            label += " (services)"
        return {
            "label": label,
            "group": _compact([w.to_group() for w in self.work]),
            "pool": self.pool,
        }


@dataclass(frozen=True)
class ModuleRun:
    module: str
    exit_code: int


@dataclass
class Outcome:
    """How one module's run ended: the record it writes and the exit code it returns."""

    status: Status
    reason: str = ""
    classified: list[tuple[str, str]] = field(default_factory=list)
    diffs: str = ""
    gap_lines: list[int] = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        return 0 if self.status in (Status.PASS, Status.SKIP) else 1


class UsageError(Exception):
    """A `module` invocation that cannot run; exits 2."""


def _compact(value: object) -> str:
    return json.dumps(value, separators=(",", ":"))


def _say(*lines: str) -> None:
    for line in lines:
        print(line, file=sys.stderr, flush=True)


def mutant_workers() -> int:
    """Return half the threads: eight workers measured clean on the 16-thread box (2026-09-17)."""
    threads = os.cpu_count() or 2
    return max(threads // 2, 1)


def workdir_base() -> Path:
    """Return where module copies live: tmpfs when it has room, else apps/api."""
    explicit = os.environ.get("MUTMUT_WORKDIR_BASE")
    if explicit:
        return Path(explicit)
    if TMPFS.is_dir() and os.access(TMPFS, os.W_OK):
        if shutil.disk_usage(TMPFS).free > TMPFS_MIN_FREE_BYTES:
            return TMPFS
    return API_ROOT


def venv_python() -> Path:
    for candidate in (REPO_ROOT / ".venv/bin/python", API_ROOT / ".venv/bin/python"):
        if os.access(candidate, os.X_OK):
            return candidate
    raise SystemExit("ERROR: mutation.py — venv python not found (run nx run api:sync first).")


def verdict_root() -> Path:
    """Ask `verdict.py dir` where lane verdicts go; never derive it."""
    result = subprocess.run(
        [str(venv_python()), str(SCRIPT_DIR / "verdict.py"), "dir"],
        capture_output=True,
        text=True,
        check=False,
    )
    resolved = result.stdout.strip()
    if result.returncode != 0 or not resolved:
        raise SystemExit(
            "ERROR: mutation.py — 'verdict.py dir' failed; cannot place the lane verdicts.\n"
            + result.stderr
        )
    return Path(resolved)


# ── matrix / plan ────────────────────────────────────────────────────────────


def _detector_output(paths: Sequence[str]) -> str:
    """Return what lib/mutation_matrix.py prints for these candidate module paths."""
    return subprocess.run(
        [sys.executable, str(LIB / "mutation_matrix.py")],
        input="".join(f"{p}\n" for p in paths),
        stdout=subprocess.PIPE,
        text=True,
        check=True,
        cwd=REPO_ROOT,
    ).stdout


def _parse_matrix(text: str) -> list[ModuleWork]:
    entries = json.loads(text)
    if not isinstance(entries, list):
        raise SystemExit("mutation matrix: the detector did not print a JSON list")
    return [ModuleWork.from_matrix(entry) for entry in entries]


def changed_matrix() -> str:
    """Return the matrix JSON for this diff: the detector's answer over its changed app modules."""
    changed = subprocess.run(
        [str(SCRIPT_DIR / "changes.sh"), "files", "py"],
        stdout=subprocess.PIPE,
        text=True,
        check=True,
        cwd=REPO_ROOT,
    ).stdout.strip()
    if not changed:
        return "[]"
    if changed == "__FULL__":
        _say(
            "mutation matrix: push/full-scan event — skipping "
            "(diff-based check; already gated on the originating PR)"
        )
        return "[]"
    # Entry points and __init__ files are not mutation targets.
    candidates = [
        path
        for path in changed.splitlines()
        if path.startswith("apps/api/app/")
        and path.endswith(".py")
        and not path.endswith(("app/main.py", "app/worker.py", "__init__.py"))
    ]
    return _detector_output(candidates).strip()


def cmd_matrix(_args: list[str]) -> int:
    print(changed_matrix())
    return 0


def pack(modules: Sequence[ModuleWork]) -> list[Shard]:
    """Split modules into at most MAX_SHARDS homogeneous shards, round-robin per pool.

    The budget is the whole plan's: every live pool gets one shard and the
    rest go to whichever pool carries the most modules per shard it has.
    """
    members = {
        "services": [m for m in modules if m.needs_services],
        "unit": [m for m in modules if not m.needs_services],
    }
    live = {pool: members[pool] for pool in POOLS if members[pool]}
    counts = dict.fromkeys(live, 1)
    while sum(counts.values()) < MAX_SHARDS:
        hungry = [pool for pool in live if counts[pool] < len(live[pool])]
        if not hungry:
            break
        counts[max(hungry, key=lambda pool: len(live[pool]) / counts[pool])] += 1
    shards: list[Shard] = []
    for pool in POOLS:
        if pool not in live:
            continue
        packed: list[list[ModuleWork]] = [[] for _ in range(counts[pool])]
        for index, work in enumerate(live[pool]):
            packed[index % len(packed)].append(work)
        shards.extend(Shard(pool, tuple(group)) for group in packed)
    return shards


def cmd_plan(_args: list[str]) -> int:
    modules = _parse_matrix(changed_matrix())
    shards = pack(modules)
    include = [shard.matrix_entry(n, len(shards)) for n, shard in enumerate(shards, start=1)]
    # The label alone is the matrix value, so the job row reads `mutation
    # (<label>)`; the job looks its group and pool up in shard_defs.
    shard_defs = {
        entry["label"]: {"group": entry["group"], "pool": entry["pool"]} for entry in include
    }
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as handle:
            handle.write(f"shards={_compact([entry['label'] for entry in include])}\n")
            handle.write(f"shard_defs={_compact(shard_defs)}\n")
            handle.write(f"count={len(include)}\n")
    if len(shards) < len(modules):
        print(f"{len(modules)} module(s) packed into {len(shards)} shards (matrix job limit)")
    else:
        print(f"{len(modules)} module(s) to mutate, one shard each")
    for entry in include:
        print(f"  [{entry['pool']:8}] {entry['label']}")
    return 0


# ── shard ────────────────────────────────────────────────────────────────────


def parse_group(raw: str) -> list[ModuleWork]:
    entries = json.loads(raw)
    if not isinstance(entries, list) or not entries:
        raise ValueError("group is empty")
    return [ModuleWork.from_group(entry) for entry in entries]


def unreachable_service() -> str | None:
    """Return why the contract tier's services cannot be reached, or None when both answer."""
    for name, fallback in (("MONGO_DB", 27017), ("REDIS_URL", 6379)):
        url = os.environ.get(name, "")
        if not url:
            return f"{name} is unset — nothing published this lane service endpoints"
        parsed = urlparse(url)
        host, port = parsed.hostname or "localhost", parsed.port or fallback
        try:
            socket.create_connection((host, port), timeout=5).close()
        except OSError as exc:
            return f"{name} at {host}:{port} is unreachable: {exc}"
    return None


def services_precondition(work: Sequence[ModuleWork]) -> str | None:
    """Return why this shard must not run, or None; drops an inherited flag a unit shard must not see.

    A contract test without services SKIPS, so its mutants read as uncovered
    (a false green); USE_REAL_SERVICES on a unit shard swaps the global mongodb
    mock for a real client, so every mutant dies of a connection error.
    """
    if any(w.needs_services for w in work):
        if os.environ.get("USE_REAL_SERVICES") != "1":
            return (
                f"this shard maps {SERVICES_TIER} tests but USE_REAL_SERVICES is not 1 — every "
                "contract test would skip and its mutants would be reported as uncovered rather "
                "than surviving. On CI the job must run with pool=services "
                "(setup-python-test-env); locally, start the services and export "
                "USE_REAL_SERVICES=1."
            )
        problem = unreachable_service()
        if problem:
            print(problem, file=sys.stderr)
            return (
                f"this shard maps {SERVICES_TIER} tests and USE_REAL_SERVICES=1, but the services "
                "are not reachable — the contract tests would ERROR on connect, and an erroring "
                "test kills every mutant it touches (a green shard that proved nothing)."
            )
    elif os.environ.pop("USE_REAL_SERVICES", None) == "1":
        print(
            f"mutation shard: no {SERVICES_TIER} tests in this shard — unsetting "
            "USE_REAL_SERVICES so the unit tiers keep their mocked services"
        )
    return None


@contextmanager
def cpu_slots(tokens: str) -> Iterator[None]:
    """Hold `tokens` host CPU tokens for the duration; a no-op off the box (lib/cpu-slots.sh)."""
    holder = subprocess.Popen(
        [
            "bash",
            "-c",
            _CPU_SLOT_HOLDER,
            "cpu-slots",
            str(LIB / "log.sh"),
            str(LIB / "cpu-slots.sh"),
            tokens,
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    assert holder.stdin is not None and holder.stdout is not None
    if holder.stdout.readline().strip() != "held":
        holder.wait()
        raise SystemExit("mutation shard: the CPU-slot holder exited before taking its tokens")
    try:
        yield
    finally:
        holder.stdin.close()
        holder.wait()


@contextmanager
def shard_base() -> Iterator[Path | None]:
    """Stage ONE real copy of app/ + tests/ + scripts/ that every module hardlinks."""
    base = workdir_base() / f".mutation-base-{os.getpid()}"
    shutil.rmtree(base, ignore_errors=True)
    staged: Path | None = base
    try:
        base.mkdir(parents=True)
        for tree in ("app", "tests", "scripts"):
            shutil.copytree(API_ROOT / tree, base / tree, symlinks=True)
        for name in ("pyproject.toml", "pytest.ini"):
            shutil.copy2(API_ROOT / name, base / name)
    except OSError as exc:
        print(
            f"::warning::mutation shard could not stage its base copy in {base} ({exc}) "
            "— each module will copy for itself"
        )
        shutil.rmtree(base, ignore_errors=True)
        staged = None
    try:
        yield staged
    finally:
        if staged is not None:
            shutil.rmtree(staged, ignore_errors=True)


def run_module(work: ModuleWork, log_path: Path, env: dict[str, str]) -> ModuleRun:
    """Run `module` for one entry as its own process group, killed at the per-module cap."""
    with log_path.open("a") as log:
        log.write(f"=== {work.module} ===\n")
        log.flush()
        proc = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "module",
                work.module,
                _compact(list(work.testfiles)),
                work.ranges or "[]",
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
            env=env,
            cwd=REPO_ROOT,
            start_new_session=True,
        )
        try:
            rc = proc.wait(timeout=MODULE_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
            rc = KILLED_BY_CAP
    if rc in report.TIMEOUT_EXIT_CODES:
        print(
            f"::error::mutation for {work.module} exceeded its timeout and was killed "
            "— see the log for the last phase reached"
        )
    return ModuleRun(work.module, rc)


def _without_log_suffix(path: Path) -> str:
    text = str(path)
    return text.removesuffix(".log")


def cmd_shard(_args: list[str]) -> int:
    os.chdir(REPO_ROOT)
    raw = os.environ.get("GROUP", "")
    if not raw:
        print("::error::mutation shard started with no GROUP — the plan job did not emit one")
        return 1
    try:
        work = parse_group(raw)
    except (ValueError, KeyError, TypeError) as exc:
        print(
            "::error::mutation shard could not read its GROUP — the plan job emitted "
            f"something unusable ({exc})"
        )
        return 1
    problem = services_precondition(work)
    if problem:
        print(f"::error::{problem}")
        return 1

    log_path = Path(os.environ.get("SHARD_LOG") or "shard.log").resolve()
    log_path.write_text("")
    # Both names derive from SHARD_LOG: `local` runs one shard per module in
    # one directory, and fixed names would overwrite each other's record.
    shard_verdict = Path(_without_log_suffix(log_path) + ".verdict.json")
    record_dir = Path(_without_log_suffix(log_path) + ".records")
    shutil.rmtree(record_dir, ignore_errors=True)
    record_dir.mkdir(parents=True)

    children = os.environ.get("MUTMUT_MAX_CHILDREN") or str(mutant_workers())
    print(f"mutation shard: {children} mutant worker(s), {children} host CPU token(s)", flush=True)
    env = {
        **os.environ,
        "MUTMUT_MAX_CHILDREN": children,
        "MUTATION_VERDICT_DIR": str(record_dir),
        "GAIA_REPO_ROOT": str(REPO_ROOT),
    }
    with cpu_slots(children), shard_base() as base:
        if base is not None:
            env["MUTMUT_SHARD_BASE"] = str(base)
        runs = [run_module(entry, log_path, env) for entry in work]

    # tail, never the whole file: a busy shard log is 13MB, and feeding that
    # through the runner's live-log pipe is where this step used to freeze.
    print(f"--- {log_path.name} (last 200KB; full file in the artifact) ---")
    with log_path.open("rb") as handle:
        handle.seek(max(log_path.stat().st_size - SHARD_LOG_TAIL_BYTES, 0))
        sys.stdout.write(handle.read().decode("utf-8", "replace"))
    sys.stdout.flush()

    verdicts = []
    for run in runs:
        record = record_dir / f"{report.module_slug(run.module)}.json"
        if record.exists():
            verdicts.append(report.from_dict(json.loads(record.read_text())))
        else:
            verdicts.append(report.missing_record_verdict(run.module, run.exit_code, "apps/api"))
    report.report_shard(
        verdicts, repo_root=REPO_ROOT, verdict_out=verdict_root(), out=shard_verdict
    )
    shutil.rmtree(record_dir)

    failed = [run for run in runs if run.exit_code != 0]
    if not failed:
        print("Mutation shard OK — every module clean")
        return 0
    names = " ".join(run.module for run in failed)
    shard_lane = os.environ.get("SHARD_LANE")
    if shard_lane:
        # The shard's own row: its modules' verdicts carry the findings.
        subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / report.VERDICT_SCRIPT),
                "emit",
                "--lane",
                shard_lane,
                "--status",
                "fail",
                "--summary",
                f"{len(failed)} of {len(runs)} module(s) did not pass: {names}",
                "--out",
                str(verdict_root()),
            ],
            check=True,
        )
    print(f"::error::mutation failed for: {names}")
    return failed[-1].exit_code


# ── local ────────────────────────────────────────────────────────────────────


def _local_status(work: ModuleWork, rc: int, log_dir: Path) -> str:
    """Read one local shard's outcome off its replay record and exit code, never its log."""
    if rc == 0:
        return "pass"
    record = log_dir / f"{work.module.replace('/', '_')}.verdict.json"
    if record.exists():
        modules = json.loads(record.read_text()).get("modules", [])
        if modules and modules[0].get("status") in (Status.SURVIVORS, Status.GAP):
            return "survivors"
    return "error"


def cmd_local(args: list[str]) -> int:
    os.chdir(REPO_ROOT)
    shutil.rmtree(LOCAL_LOG_DIR, ignore_errors=True)
    LOCAL_LOG_DIR.mkdir(parents=True)
    # Cleared once, and only this lane's subtree: a stale module from an earlier
    # local run would otherwise consolidate as a lane of this one.
    shutil.rmtree(verdict_root() / "mutation", ignore_errors=True)

    if args:
        modules = _parse_matrix(
            _detector_output([f"apps/api/{a.removeprefix('apps/api/')}" for a in args])
        )
    else:
        modules = _parse_matrix(changed_matrix())
    if not modules:
        print("mutation: no changed app modules — nothing to mutate")
        return 0
    print(f"mutation: {len(modules)} module(s), logs in {LOCAL_LOG_DIR}/")

    # Two levels of parallelism multiply (modules x mutant workers), so they
    # split one budget, two cores left for the OS; most runs touch one or two
    # modules, so the weighting favours mutmut's children.
    nproc = os.cpu_count() or 2
    budget = int(os.environ.get("MUTATION_CPU_BUDGET") or (nproc - 2 if nproc > 3 else 1))
    jobs = max(min(int(os.environ.get("MUTATION_JOBS") or len(modules)), 4, budget), 1)
    children = os.environ.get("MUTMUT_MAX_CHILDREN") or str(max(budget // jobs, 1))
    print(
        f"mutation: {len(modules)} module(s) on {nproc} vCPUs — budget {budget}, "
        f"{jobs} in parallel x {children} mutant worker(s)",
        flush=True,
    )

    def run_one(work: ModuleWork) -> tuple[ModuleWork, str]:
        slug = work.module.replace("/", "_")
        with (LOCAL_LOG_DIR / f"{slug}.out").open("w") as out:
            rc = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), "shard"],
                env={
                    **os.environ,
                    "GROUP": _compact([work.to_group()]),
                    "SHARD_LOG": str(LOCAL_LOG_DIR / f"{slug}.log"),
                    "MUTMUT_MAX_CHILDREN": children,
                },
                stdout=out,
                stderr=subprocess.STDOUT,
                check=False,
            ).returncode
        status = _local_status(work, rc, LOCAL_LOG_DIR)
        log = LOCAL_LOG_DIR / f"{slug}.log"
        line = {
            "pass": f"  pass      {work.module}",
            "survivors": f"  SURVIVORS {work.module}  ({log})",
            "error": f"  ERROR     {work.module}  (run produced no result; {log})",
        }[status]
        print(line, flush=True)
        return work, status

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        outcomes = list(pool.map(run_one, modules))

    errored = [w.module for w, status in outcomes if status == "error"]
    failed = [w.module for w, status in outcomes if status == "survivors"]
    if errored:
        print("\nmutation: module(s) produced NO result (crash or timeout, not survivors):")
        for module in errored:
            print(f"  {module}")
        print("  Retry these with MUTATION_JOBS=1 before believing anything about them.")
    if failed:
        print("\nmutation: module(s) with survivors on changed lines:")
        for module in failed:
            print(f"  {module}")
    if errored or failed:
        return 1
    print(f"mutation: all {len(modules)} module(s) clean")
    return 0


# ── module ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ModuleRequest:
    module: str
    testfiles: tuple[str, ...]
    ranges: str

    @classmethod
    def from_args(cls, args: list[str]) -> ModuleRequest:
        if not args:
            raise UsageError(
                "usage: mutation.py module <module> [test-file] (e.g. app/services/foo.py)"
            )
        module = args[0].removeprefix("apps/api/")
        if not module.startswith("app/"):
            raise UsageError("module must be under app/ (e.g. app/services/foo.py)")
        rel = Path(module.removeprefix("app/"))
        testfile_arg = (
            args[1] if len(args) > 1 and args[1] else f"tests/unit/{rel.parent}/test_{rel.stem}.py"
        )
        # Omitted ranges are derived by the same code the lane uses, so a local
        # run scopes identically instead of to a scope that cannot fail.
        ranges = args[2] if len(args) > 2 else ""
        if not ranges:
            scope = subprocess.run(
                [sys.executable, str(LIB / "mutation_matrix.py"), "--scope", module],
                stdout=subprocess.PIPE,
                text=True,
                check=False,
                cwd=REPO_ROOT,
            )
            if scope.returncode != 0:
                # The detector has already said why on stderr.
                raise SystemExit(1)
            ranges = scope.stdout.strip()
        if ranges in ("", "[]"):
            raise UsageError(
                f"mutation: empty line scope for {module} — refusing to run.\n"
                "  An empty scope classifies every survivor as out-of-scope and exits 0,\n"
                "  which reports a pass it did not earn. Pass explicit ranges as argument 3,\n"
                "  or let them be derived (omit it) from the diff against the base branch."
            )
        testfiles = _testfiles(testfile_arg)
        for testfile in testfiles:
            if not (API_ROOT / testfile).is_file():
                raise UsageError(
                    f"test file not found: {testfile} — pass it explicitly as the second argument."
                )
        return cls(module=module, testfiles=testfiles, ranges=ranges)


def _testfiles(arg: str) -> tuple[str, ...]:
    """Read argument 2: ONE path as a human types it, or the lane's compact JSON array."""
    if not arg.startswith("["):
        return (arg,)
    try:
        files = json.loads(arg)
    except json.JSONDecodeError as exc:
        raise UsageError(f"argument 2 starts with '[' but is not valid JSON: {exc}") from exc
    if not isinstance(files, list) or not all(isinstance(f, str) for f in files):
        raise UsageError("argument 2 must be a JSON array of path strings")
    if not files:
        raise UsageError("argument 2 is an empty JSON array — no test file to run")
    return tuple(files)


class Phases:
    """Print a breadcrumb per phase, so a run killed at its cap says where it hung."""

    def __init__(self) -> None:
        self.start = time.monotonic()

    def __call__(self, name: str) -> None:
        _say(f"[phase +{int(time.monotonic() - self.start)}s] {name}")


def copy_workdir(request: ModuleRequest, workdir: Path) -> None:
    """Give the module a private tree: hardlinks of the shard's base, or a real copy.

    Never symlinks: one inode under two sys.path entries makes CPython refuse
    to load the module twice. The two files this run WRITES are real copies.
    """
    shutil.rmtree(workdir, ignore_errors=True)
    base = os.environ.get("MUTMUT_SHARD_BASE")
    if base and Path(base).is_dir():
        try:
            shutil.copytree(base, workdir, symlinks=True, copy_function=os.link)
        except OSError:
            shutil.rmtree(workdir, ignore_errors=True)
        else:
            for private in ("pyproject.toml", request.module):
                (workdir / private).unlink()
                shutil.copy2(API_ROOT / private, workdir / private)
            return
    workdir.mkdir(parents=True)
    for tree in ("app", "tests", "scripts"):
        shutil.copytree(API_ROOT / tree, workdir / tree, symlinks=True)
    # pytest.ini carries asyncio_mode=auto; under /dev/shm nothing above has it.
    for name in ("pyproject.toml", "pytest.ini"):
        shutil.copy2(API_ROOT / name, workdir / name)


def configure_mutmut(request: ModuleRequest, workdir: Path) -> None:
    """Scope mutmut 3.x to this module and its tests — it scopes only through config."""
    selection = ", ".join(json.dumps(f) for f in request.testfiles)
    replacement = (
        "[tool.mutmut]\n"
        f'source_paths = ["{request.module}"]\n'
        'also_copy = ["app", "tests", "scripts", "pytest.ini"]\n'
        # 20, not 8: a deeper call chain silently unlinked tests from mutants.
        "max_stack_depth = 20\n"
        'do_not_mutate_patterns = ["# pragma: no mutate"]\n'
        "debug = true\n"
        f"pytest_add_cli_args_test_selection = [{selection}]\n"
        'pytest_add_cli_args = ["-p", "no:xdist", "-p", "mutmut_in_test_marker", '
        '"-o", "timeout_func_only=true", "-o", '
        f"'addopts={PLUGIN_FENCE} --timeout={MUTANT_TEST_TIMEOUT}']\n"
    )
    pyproject = workdir / "pyproject.toml"
    text = re.sub(r"(?ms)^\[tool\.mutmut\].*?(?=^\[|\Z)", replacement, pyproject.read_text())
    pyproject.write_text(text)


def _tee(source: IO[bytes], log: IO[bytes]) -> None:
    for chunk in iter(source.readline, b""):
        log.write(chunk)
        log.flush()
        sys.stderr.buffer.write(chunk)
        sys.stderr.buffer.flush()


def run_mutmut(request: ModuleRequest, venv: Path, workdir: Path) -> tuple[int, str]:
    """Run mutmut in its own session, teed into mutmut.log; return its exit code and output."""
    children = os.environ.get("MUTMUT_MAX_CHILDREN") or str(mutant_workers())
    # Contract tests flush a Redis DB keyed on PYTEST_XDIST_WORKER, which mutmut
    # never sets: parallel mutants would flush each other's keys (a false kill).
    if any(f.startswith(SERVICES_TIER) for f in request.testfiles):
        children = "1"
        _say(
            f"mutation: {request.module} maps a contract test — one mutant worker so "
            "real-Redis teardown cannot race"
        )
    env = {
        **os.environ,
        "MUTMUT_MAX_CHILDREN": children,
        "MUTMUT_CHANGED_RANGES": request.ranges,
        "MUTMUT_SCOPED_MODULE": request.module,
        IN_TEST_DIR_ENV: str(workdir / IN_TEST_DIR),
        "PYTHONPATH": str(REPO_ROOT / "scripts" / "test")
        + os.pathsep
        + os.environ.get("PYTHONPATH", ""),
    }
    # The patches load first: decorated functions become targets, generation is
    # scoped to the changed lines, and the also_copy tree is hardlinked. The
    # C-extension-heavy imports happen before the stats pass can unload them.
    run_args = ["run", "--max-children", children]
    child_code = (
        "import mutmut_decorated_patch; "
        "import mutmut_diff_scope; "
        "import mutmut_hardlink_copy; "
        "import sys as _sys; "
        f"_sys.argv += {run_args!r}; "
        "from mutmut.__main__ import cli; cli()"
    )
    (workdir / IN_TEST_DIR).mkdir()
    log_path = workdir / "mutmut.log"
    with log_path.open("wb") as log:
        proc = subprocess.Popen(
            [str(venv), "-c", child_code],
            cwd=workdir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        assert proc.stdout is not None
        tee = threading.Thread(target=_tee, args=(proc.stdout, log), daemon=True)
        tee.start()
        try:
            rc = proc.wait(timeout=MUTMUT_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            rc = MUTMUT_TIMED_OUT
        finally:
            # Reap the detached session on EVERY path: a straggler there survives
            # the step abort, which walks only the step's own process tree.
            with suppress(ProcessLookupError, PermissionError):
                os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
            tee.join()
    return rc, log_path.read_text(errors="replace")


def _pytest_passes(
    venv: Path, cwd: Path, testfiles: Sequence[str], extra: Sequence[str], log: Path
) -> bool:
    with log.open("w") as out:
        return (
            subprocess.run(
                [str(venv), "-m", "pytest", "-q", *testfiles, *extra, "-o", PLAIN_RUN_ADDOPTS],
                cwd=cwd,
                stdout=out,
                stderr=subprocess.STDOUT,
                check=False,
            ).returncode
            == 0
        )


def diagnose(log: str) -> RunFailure | None:
    return next((failure for failure in RunFailure if failure.value in log), None)


def failed_run_outcome(
    request: ModuleRequest, venv: Path, workdir: Path, log: str
) -> Outcome | None:
    """Judge a mutmut run that exited non-zero; None when its results are still worth reading."""
    module = request.module
    failure = diagnose(log)
    if failure is None:
        return no_state_outcome(module, workdir, log)
    if failure is RunFailure.NO_COVERING_TEST:
        # "No covering test" is two facts: nothing mutatable on the changed lines
        # (silence is right), or executable lines no test reaches (the gap).
        # mutmut resolves [tool.mutmut] from the cwd, and only the workdir copy has it.
        gap = subprocess.run(
            [str(venv), str(LIB / "mutation_gap.py"), str(API_ROOT / module), request.ranges],
            cwd=workdir,
            stdout=subprocess.PIPE,
            text=True,
            check=True,
        ).stdout
        gap_lines = [int(token) for token in gap.split()]
        if gap_lines:
            _say(
                f"MUTATION FAILED — changed code no test reaches in {module}:",
                f"      line(s) {' '.join(map(str, gap_lines))}",
                "      These are executable lines inside a function that this PR added or",
                "      changed, and none of the module's mapped tests execute them, so no",
                "      mutant there could ever be killed. Write a test that runs them and",
                "      asserts what they do — or, if they are only reachable through the",
                "      contract tier, say so: that tier does not run in this lane.",
            )
            return Outcome(Status.GAP, gap_lines=gap_lines)
        return _skip(
            f"SKIP: {module} — nothing on the changed lines for a test to pin (imports, "
            "constants, docstrings, decorators, or code inside a decorated function, which "
            "mutmut 3.7 cannot mutate)."
        )
    if failure is RunFailure.CLEAN_RUN_FAILED:
        # Module-level state can leak across mutmut's one-process phases: the
        # tests passing in the plain copy is what says it is mutmut, not them.
        plain = workdir / "plain-check.log"
        if _pytest_passes(
            venv, workdir, request.testfiles, ("-p", "no:randomly", "-p", "no:random-order"), plain
        ):
            return _skip(
                f"SKIP: {module} — the tests pass in the plain copy but fail under mutmut's "
                "single-process phase transitions (module-level state does not survive "
                "stats->clean->mutants in one process, a documented mutmut 3.7 limitation)."
            )
        return _error(f"REAL FAILURE: {module}'s tests fail in the plain copy too — see {plain}")
    if failure is RunFailure.BAD_TEST_COMMAND:
        mutants = workdir / "mutants"
        check = workdir / "mutants-tree-check.log"
        extra = ("--rootdir=.", "-p", "no:randomly", "-p", "no:random-order", "-p", "no:xdist")
        if mutants.is_dir() and _pytest_passes(venv, mutants, request.testfiles, extra, check):
            return _skip(
                f"SKIP: {module} — the same pytest run passes on mutmut's instrumented tree out "
                "of process, but fails inside mutmut's in-process stats tracer (import-time work "
                "in the module trips it, a documented mutmut 3.7 limitation)."
            )
        return _error(
            f"REAL FAILURE: mutmut could not run {' '.join(request.testfiles)} (pytest "
            f"usage/collection error), and the run also fails on the instrumented tree — see {check}"
        )
    return _skip(
        f"SKIP: {module} — mutmut cannot collect stats for a module that invokes its own "
        "function at import time (the trampoline resolves the calling frame, which during "
        "import is <frozen importlib._bootstrap>)."
    )


def no_state_outcome(module: str, workdir: Path, log: str) -> Outcome | None:
    """Return the error of a failed run that left no mutmut state; None when it left some."""
    if (workdir / "mutants" / "mutmut-stats.json").exists():
        # A non-zero exit AFTER the mutants ran (the loguru teardown crash) leaves
        # the results as the source of truth; an incomplete run fails there.
        return None
    # `mise ci:remote` keys on this exact line in the shard log artifact.
    _say("MUTATION RUN FAILED (no state produced) — see mutmut's output above.")
    timed_out = len(_TIMED_OUT_TEST.findall(log))
    if timed_out:
        return Outcome(
            Status.ERROR,
            f"{module} reached no verdict: {timed_out} test(s) hit the {MUTANT_TEST_TIMEOUT}s "
            "per-test timeout before mutmut graded a mutant, so no survivors were measured",
        )
    return Outcome(
        Status.ERROR,
        f"{module} reached no verdict: mutmut produced no state and no test hit the "
        f"{MUTANT_TEST_TIMEOUT}s per-test timeout, so no mutant was graded and no survivors "
        "were measured — see shard.log",
    )


def _skip(reason: str) -> Outcome:
    _say(reason)
    return Outcome(Status.SKIP, reason)


def _error(reason: str) -> Outcome:
    _say(reason)
    return Outcome(Status.ERROR, reason)


def read_results(venv: Path, workdir: Path) -> list[tuple[str, str]] | Outcome:
    """Return every mutant with mutmut's status, or the error outcome of an unreadable read.

    Only lines naming a mutant count: a banner mutmut prints there is not one.
    """
    result = subprocess.run(
        [str(venv), "-m", "mutmut", "results", "--all", "True"],
        cwd=workdir,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return _error(f"MUTATION RESULTS UNREADABLE — 'mutmut results' failed:\n{result.stderr}")
    return [
        (match["name"], match["status"])
        for match in map(_RESULT_LINE.match, result.stdout.splitlines())
        if match
    ]


def fork_crash_exit_codes(request: ModuleRequest, workdir: Path) -> set[int]:
    """Return the distinct worker exit codes mutmut recorded for this module's mutants."""
    meta = workdir / "mutants" / f"{request.module}.meta"
    if not meta.is_file():
        return set()
    codes = json.loads(meta.read_text())["exit_code_by_key"].values()
    return {code for code in codes if code is not None}


def killed_in_test(workdir: Path) -> dict[str, str]:
    """Map each mutant whose child was killed inside a test body to that test's node id."""
    return {marker.name: marker.read_text() for marker in (workdir / IN_TEST_DIR).iterdir()}


def classify(
    venv: Path, name: str, status: str, request: ModuleRequest, workdir: Path
) -> str | None:
    """Return the classifier's verdict for one mutant, or None when it gave none we know."""
    line = f"    {name}: {status}"
    verdict = subprocess.run(
        [
            str(venv),
            str(REPO_ROOT / "scripts/test/mutation_classify.py"),
            line,
            str(workdir),
            request.ranges,
            request.module,
        ],
        stdout=subprocess.PIPE,
        text=True,
        check=False,
    ).stdout.strip()
    kind = verdict.partition(":")[0]
    if kind not in CLASSIFIER_KINDS or (kind != "EQUIV" and ":" not in verdict):
        _say(
            f"MUTATION CLASSIFIER FAILED on: {line}",
            f"  verdict='{verdict}' — a survivor with no verdict must not vanish from every bucket.",
        )
        return None
    return verdict


def _incomplete_run(module: str, workdir: Path, counts: Counter[str], total: int) -> Outcome | None:
    """Return the verdict of a run that did not grade every mutant, or None when it did."""
    if total == 0:
        if not (workdir / "mutmut.log").stat().st_size and not (workdir / "mutants").is_dir():
            # No results, an empty log and no mutants/ tree: the child never ran,
            # which is not the zero-mutant skip below, where mutmut said so.
            _say(
                "MUTATION RUN PRODUCED NO RESULTS — the mutmut child did not run.",
                f"  Nothing was mutated and nothing was proven about {module}.",
            )
            return Outcome(Status.ERROR, "mutmut produced no results — the child did not run")
        return _skip(f"mutmut generated no mutants on the changed lines of {module}")
    if counts["not checked"]:
        return _error(
            f"MUTATION RUN INCOMPLETE — {counts['not checked']} mutant(s) were never checked; "
            "the run was interrupted."
        )
    unbucketed = sum(n for status, n in counts.items() if status not in COUNTED_STATUSES)
    if counts["segfault"] or unbucketed:
        return _error(
            f"MUTATION RUN INCOMPLETE — {counts['segfault']} segfault(s) and {unbucketed} "
            f"unbucketed mutant(s) of {total} reached NO verdict (on macOS see the NO_PROXY "
            "note in tests/conftest.py)."
        )
    return None


def _ungraded_outcome(
    request: ModuleRequest, workdir: Path, counts: Counter[str], total: int
) -> Outcome:
    """Judge a run where no mutant was killed or survived: a timeout, the fork crash, or nothing."""
    module = request.module
    # The chromadb carve-out: EVERY mutant died in the fork (exit codes from
    # mutmut's own record) and none inside a test, where a timeout dies.
    in_test = killed_in_test(workdir)
    if in_test:
        mutant, test = min(in_test.items())
        return _error(
            f"MUTATION TIMED OUT — {len(in_test)} of {total} mutant(s) of {module} were "
            f"killed inside a test body (first: {mutant} in {test}) and not one was killed "
            "or survived: the mutants hang the tests, so no survivors were measured."
        )
    codes = fork_crash_exit_codes(request, workdir)
    if codes and codes <= FORK_CRASH_EXIT_CODES:
        return _skip(
            f"MUTATION SKIPPED — {module} was NOT graded: all {total} mutant(s) died in the "
            "fork, not in a test (a chromadb client's Rust core cannot survive fork()). "
            f"Buckets: {counts['suspicious']} suspicious, {counts['timeout']} timeout."
        )
    return _error(
        f"MUTATION PROVED NOTHING — all {total} mutant(s) of {module} ran and not one was "
        f"killed or survived ({counts['suspicious']} suspicious, {counts['no tests']} no "
        "tests): fix the run or pick a test file that exercises the module."
    )


def _classified(
    request: ModuleRequest, venv: Path, workdir: Path, results: list[tuple[str, str]], status: str
) -> list[tuple[str, str]] | Outcome:
    """Classify every mutant with this mutmut status; an ERROR outcome if one gets no verdict."""
    classified: list[tuple[str, str]] = []
    for name, mutant_status in results:
        if mutant_status != status:
            continue
        verdict = classify(venv, name, mutant_status, request, workdir)
        if verdict is None:
            return Outcome(Status.ERROR, f"the survivor classifier gave no verdict for {name}")
        classified.append((name, verdict))
    return classified


def _survivor_diffs(venv: Path, workdir: Path, names: list[str]) -> str:
    """Return `mutmut show` for each real survivor, concatenated."""
    diffs = ""
    for name in names:
        shown = subprocess.run(
            [str(venv), "-m", "mutmut", "show", name],
            cwd=workdir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        if shown.returncode != 0:
            _say(f"  (diff of {name} unavailable)")
        diffs += shown.stdout
    return diffs


def graded_outcome(request: ModuleRequest, venv: Path, workdir: Path, phase: Phases) -> Outcome:
    """Judge a run from mutmut's results: complete, graded, and what survived where."""
    phase("collect results")
    results = read_results(venv, workdir)
    if isinstance(results, Outcome):
        return results
    counts = Counter(status for _name, status in results)
    total = len(results)
    incomplete = _incomplete_run(request.module, workdir, counts, total)
    if incomplete is not None:
        return incomplete
    if counts["suspicious"]:
        _say(
            f"NOTE: {counts['suspicious']} of {total} mutant(s) came back 'suspicious' — the test "
            "process exited in none of the ways mutmut reads, so they prove NOTHING either way."
        )
    if not counts["killed"] and not counts["survived"]:
        return _ungraded_outcome(request, workdir, counts, total)

    phase("classify survivors")
    classified = _classified(request, venv, workdir, results, "survived")
    if isinstance(classified, Outcome):
        return classified
    no_tests = _classified(request, venv, workdir, results, "no tests")
    if isinstance(no_tests, Outcome):
        return no_tests
    uncovered_changed = [name for name, verdict in no_tests if verdict.startswith("CHANGED:")]
    _notes(classified, uncovered_changed, counts["no tests"])

    real = [name for name, verdict in classified if verdict.startswith("CHANGED:")]
    diffs = ""
    if real:
        phase("collect survivor diffs")
        diffs = _survivor_diffs(venv, workdir, real)
        _say(diffs)
    return Outcome(Status.SURVIVORS if real else Status.PASS, classified=classified, diffs=diffs)


def _notes(classified: list[tuple[str, str]], uncovered_changed: list[str], no_tests: int) -> None:
    """Print every exclusion before the verdict, so none is invisible on a failing run."""
    if uncovered_changed:
        _say(
            f"NOTE: {len(uncovered_changed)} mutant(s) ON CHANGED LINES have NO covering test —",
            "      a coverage hole wearing a clean result:",
            *(f"  {name}" for name in uncovered_changed),
        )
    if no_tests:
        _say(f"NOTE: {no_tests} mutant(s) had no covering test across the WHOLE module.")
    for kind, note in (
        ("UNCHANGED", "survivor(s) on lines the PR did not touch (diff-driven gate):"),
        ("EQUIV", "provably equivalent mutant(s) (see scripts/test/mutation_classify.py):"),
        (
            "LOGGING",
            "mutant(s) excluded as logging-only (log.debug/log.info never reach the wide event):",
        ),
        ("LINTED", "mutant(s) excluded as lint-caught (the tool-dump-boundary lint, #917):"),
    ):
        names = [name for name, verdict in classified if verdict.partition(":")[0] == kind]
        if names:
            _say(f"NOTE: {len(names)} {note}", *(f"  {name}" for name in names))


def mutate(request: ModuleRequest, venv: Path, workdir: Path) -> Outcome:
    phase = Phases()
    phase("copy workdir")
    copy_workdir(request, workdir)
    configure_mutmut(request, workdir)
    phase("mutmut run")
    _say(f"mutating {request.module} (tests: {' '.join(request.testfiles)}) ...")
    rc, log = run_mutmut(request, venv, workdir)
    if rc != 0:
        judged = failed_run_outcome(request, venv, workdir, log)
        if judged is not None:
            return judged
    return graded_outcome(request, venv, workdir, phase)


def _record(request: ModuleRequest, outcome: Outcome, directory: Path) -> None:
    verdict = report.add_classified(
        report.ModuleVerdict(
            module=request.module,
            status=outcome.status.value,
            path=f"apps/api/{request.module}",
            testfiles=list(request.testfiles),
            gap_lines=list(outcome.gap_lines),
            reason=outcome.reason or None,
        ),
        API_ROOT / request.module,
        outcome.classified,
        outcome.diffs,
    )
    report.write_record(directory / f"{report.module_slug(request.module)}.json", verdict)
    if verdict.survivors:
        print(report.render_report(verdict), flush=True)


def _terminate(signum: int, _frame: FrameType | None) -> None:
    raise SystemExit(128 + signum)


def cmd_module(args: list[str]) -> int:
    record_dir = os.environ.get("MUTATION_VERDICT_DIR")
    try:
        request = ModuleRequest.from_args(args)
    except UsageError as exc:
        _say(str(exc))
        module = args[0].removeprefix("apps/api/") if args else ""
        if record_dir and module.startswith("app/"):
            unrunnable = ModuleRequest(module=module, testfiles=(), ranges="")
            _record(unrunnable, Outcome(Status.ERROR, str(exc).splitlines()[0]), Path(record_dir))
        return 2
    venv = venv_python()
    os.environ.setdefault("MUTMUT_MAX_CHILDREN", str(mutant_workers()))
    workdir = workdir_base() / f".mutation-{os.getpid()}"
    signal.signal(signal.SIGTERM, _terminate)
    signal.signal(signal.SIGINT, _terminate)
    try:
        outcome = mutate(request, venv, workdir)
        _record(request, outcome, Path(record_dir) if record_dir else workdir)
    finally:
        if not os.environ.get("MUTMUT_KEEP_WORKDIR"):
            shutil.rmtree(workdir, ignore_errors=True)
    if outcome.status is Status.PASS:
        print(f"Mutation: OK — no survivors on changed lines in {request.module}")
    return outcome.exit_code


# ── replay ───────────────────────────────────────────────────────────────────


def cmd_replay(args: list[str]) -> int:
    """Reproduce ONE survivor from its recorded diff on a scratch copy of apps/api."""
    if len(args) < 2 or not args[0] or not args[1]:
        print(
            "usage: mutation.py replay <verdict.json|shard.log> <mutant-id|file.py:LINE>",
            file=sys.stderr,
        )
        return 2
    venv = venv_python()
    return subprocess.run(
        [
            str(venv),
            str(LIB / "mutation_report.py"),
            "replay",
            args[0],
            args[1],
            "--repo-root",
            str(REPO_ROOT),
            "--api-root",
            str(API_ROOT),
            "--python",
            str(venv),
        ],
        check=False,
    ).returncode


COMMANDS = {
    "matrix": cmd_matrix,
    "plan": cmd_plan,
    "shard": cmd_shard,
    "module": cmd_module,
    "local": cmd_local,
    "replay": cmd_replay,
}


def main(argv: list[str]) -> int:
    handler = COMMANDS.get(argv[0] if argv else "")
    if handler is None:
        print(f"mutation.py: unknown subcommand '{argv[0] if argv else ''}'", file=sys.stderr)
        print(__doc__, file=sys.stderr)
        return 2
    # Mutants run from a copy of apps/api outside the repo, so code that reads
    # a repo-root file (scripts/ci/analytics.py) is told where the repo is.
    os.environ["GAIA_REPO_ROOT"] = str(REPO_ROOT)
    return handler(argv[1:])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
