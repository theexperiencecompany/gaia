"""A module's mutmut cap and the shard's deadline (scripts/ci/mutation.py).

On PR #1799 two contract-mapped modules (repositories/conversations.py,
conversation/mongo_log.py) needed ~14-16 minutes of serial mutants and hit a
fixed 720 s cap at 452/519 and 383/521 graded, so a correct suite got no
verdict. Meanwhile a 54-module shard ran past the step timeout and was killed
with every module after the cut unreported. Nothing here runs mutmut; one test
runs a memory hog under the per-process cap a shard puts on mutmut.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
import resource
import subprocess
import sys
import time

import mutation
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
CONTRACTS = tuple(f"tests/contracts/test_log{n}.py" for n in range(8))
GIB = 1 << 30


def _work(
    mutants: int, testfiles: tuple[str, ...] = ("tests/unit/test_x.py",)
) -> mutation.ModuleWork:
    return mutation.ModuleWork(
        module="app/x.py", testfiles=testfiles, ranges="[[1,9]]", mutants=mutants
    )


def test_a_heavy_contract_module_gets_a_cap_above_the_old_fixed_one() -> None:
    # mongo_log.py's shape on #1799: 431 estimated mutants, 8 contract files.
    heavy = _work(431, CONTRACTS)

    assert heavy.mutmut_cap > 720
    assert heavy.mutmut_cap > heavy.cost


def test_a_light_module_keeps_the_floor() -> None:
    assert _work(10).mutmut_cap == mutation.MUTMUT_CAP_FLOOR_SECONDS


def test_no_cap_outlasts_what_the_deadline_leaves_after_wrap_up() -> None:
    # Bounded by the deadline, not the budget: a module costed under the budget
    # may still run longer (comms_runner.py: 26 s estimated, 561 s measured).
    assert _work(100_000, CONTRACTS).mutmut_cap == (
        mutation.SHARD_DEADLINE_SECONDS - mutation.MODULE_WRAPUP_SECONDS
    )


def test_the_cap_shrinks_to_what_the_deadline_leaves() -> None:
    seconds_left = mutation.MODULE_WRAPUP_SECONDS + 300

    assert mutation.module_cap(_work(431, CONTRACTS), seconds_left) == 300


def test_a_module_the_deadline_has_no_room_for_is_not_started(tmp_path: Path) -> None:
    run = mutation.run_module(_work(10), tmp_path / "shard.log", {}, deadline=time.monotonic())

    assert run.not_started
    assert run.exit_code == mutation.MUTMUT_TIMED_OUT
    # It never reached the log, so nothing pretends it ran.
    assert not (tmp_path / "shard.log").exists()


def test_preparation_time_comes_out_of_mutmuts_cap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # run_module kills the module at cap + wrap-up from launch, and mutmut runs in
    # its own session: a cap counted from mutmut's launch outlived that kill.
    clock = [1000.0]
    remaining: list[float] = []

    def slow_copy(_request: mutation.ModuleRequest, _workdir: Path) -> None:
        clock[0] += 200

    def fake_mutmut(
        _request: mutation.ModuleRequest, _venv: Path, _workdir: Path, deadline: float
    ) -> tuple[int, str]:
        remaining.append(deadline - clock[0])
        return mutation.MUTMUT_TIMED_OUT, ""

    monkeypatch.setenv(mutation.MUTMUT_CAP_ENV, "300")
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(mutation, "copy_workdir", slow_copy)
    monkeypatch.setattr(mutation, "configure_mutmut", lambda _request, _workdir: None)
    monkeypatch.setattr(mutation, "run_mutmut", fake_mutmut)

    request = mutation.ModuleRequest(
        module="app/x.py", testfiles=("tests/unit/test_x.py",), ranges=""
    )
    outcome = mutation.mutate(request, tmp_path / "python", tmp_path / "work")

    assert remaining == [100]
    assert outcome.status is mutation.Status.TIMED_OUT


def test_the_shard_deadline_ends_before_the_step_timeout() -> None:
    # Past the step timeout the runner kills the shard and every verdict after
    # the cut is lost; the deadline must leave room for the tail and the report.
    workflow = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text())
    step = next(
        s
        for s in workflow["jobs"]["test-mutation"]["steps"]
        if s.get("run") == "python3 scripts/ci/mutation.py shard"
    )
    assert step["timeout-minutes"] * 60 > mutation.SHARD_DEADLINE_SECONDS


def test_mutmut_and_its_workers_split_the_memory_share(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mutation, "memory_available", lambda: 16 * GIB)

    assert mutation.mutant_memory_cap(2) == int(16 * GIB * mutation.MUTANT_MEMORY_SHARE / 3)


@pytest.mark.skipif(sys.platform != "linux", reason="RLIMIT_DATA is enforced on Linux only")
def test_a_mutant_that_outgrows_the_cap_gets_memory_error_not_the_oom_killer() -> None:
    # conversation/step.py on #1799: one looping mutant took a runner from 1.1 GB to 8 GB in
    # 50 s, and the OOM killer took the whole VM ("the runner received a shutdown signal").
    # The hog waits for stdin so the cap is on before it allocates, set from the
    # parent the way run_mutmut sets it.
    hog = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import sys\nsys.stdin.read()\nchunks = []\n"
            "while True: chunks.append(bytearray(1 << 26))",
        ],
        stdin=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        resource.prlimit(hog.pid, resource.RLIMIT_DATA, (GIB, GIB))
        _, stderr = hog.communicate(input=b"", timeout=60)
    finally:
        hog.kill()
        hog.wait()

    assert hog.returncode == 1
    assert b"MemoryError" in stderr


def test_a_measured_module_is_capped_from_its_measured_cost() -> None:
    measured = dataclasses.replace(_work(10), measured=400.0)

    assert measured.cost == 400.0
    assert measured.mutmut_cap == 1200
    assert mutation.ModuleWork.from_group(measured.to_group()) == measured
