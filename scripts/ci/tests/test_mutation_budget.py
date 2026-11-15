"""A module's mutmut cap and the shard's deadline (scripts/ci/mutation.py).

On PR #1799 two contract-mapped modules (repositories/conversations.py,
conversation/mongo_log.py) needed ~14-16 minutes of serial mutants and hit a
fixed 720 s cap at 452/519 and 383/521 graded, so a correct suite got no
verdict. Meanwhile a 54-module shard ran past the step timeout and was killed
with every module after the cut unreported. Nothing here runs mutmut.
"""

from __future__ import annotations

from pathlib import Path
import time

import mutation
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
CONTRACTS = tuple(f"tests/contracts/test_log{n}.py" for n in range(8))


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
