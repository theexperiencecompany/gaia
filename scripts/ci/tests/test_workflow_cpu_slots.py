"""Every heavy nx lane in main.yml queues through the host CPU governor.

`lib/cpu-slots.sh` only governs the lanes that ask it to. A lane that sizes its
own parallelism from `runner.sh parallel` and then runs nx directly takes those
cores whether or not the box has them, and the cost lands on whichever
neighbour has a deadline: `test-typescript` was unenrolled, and a jsdom render
that takes 137 ms idle blew vitest's 5 s timeout on the loaded box, failed the
lane, and passed unchanged on the next run.

Being unenrolled is invisible — the lane is green whenever the box happens to
be quiet — so the only way to notice is a test that reads the workflow.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
MAIN_YML = REPO_ROOT / ".github" / "workflows" / "main.yml"

# The lanes whose step runs nx across the whole workspace at a parallelism it
# picked from nproc. Named rather than discovered: a new one should have to be
# added here deliberately, which is the moment to ask whether it needs slots.
GOVERNED_JOBS = ("build", "test-typescript")


@pytest.fixture(scope="module")
def workflow() -> dict[str, Any]:
    return yaml.safe_load(MAIN_YML.read_text())


@pytest.mark.parametrize("job_name", GOVERNED_JOBS)
def test_the_nx_step_holds_cpu_tokens_while_it_runs(
    workflow: dict[str, Any], job_name: str
) -> None:
    steps = workflow["jobs"][job_name]["steps"]
    nx_steps = [s for s in steps if "pnpm exec nx run-many" in s.get("run", "")]
    assert nx_steps, f"{job_name} no longer runs nx run-many — is this table stale?"

    for step in nx_steps:
        assert "runner.sh with-slots" in step["run"], (
            f"{job_name}: the nx step runs outside the CPU governor. Wrap it in "
            f'`runner.sh with-slots "$NX_PARALLEL" -- ...` so it queues against '
            f"the box's core budget instead of thrashing the concurrent lanes."
        )


@pytest.mark.parametrize("job_name", GOVERNED_JOBS)
def test_the_tokens_it_takes_match_the_parallelism_it_asks_nx_for(
    workflow: dict[str, Any], job_name: str
) -> None:
    """Holding fewer tokens than nx spawns workers is a governor that lies:
    the box budget is respected on paper while the cores are oversubscribed."""
    steps = workflow["jobs"][job_name]["steps"]
    run = next(s["run"] for s in steps if "runner.sh with-slots" in s.get("run", ""))
    # The command line only. The step's own comments explain what with-slots is
    # for and name NX_PARALLEL in prose, and a regex over the whole block reads
    # the explanation instead of the invocation.
    command = next(line for line in run.splitlines() if "runner.sh with-slots" in line)

    held = re.search(r"with-slots\s+\"?\$\{?([A-Za-z_]\w*)\}?\"?", command)
    requested = re.search(r"--parallel=\"?\$\{?([A-Za-z_]\w*)\}?\"?", command)
    assert held and requested, f"{job_name}: could not read the slot/parallel pair from the step"
    assert held.group(1) == requested.group(1), (
        f"{job_name}: takes {held.group(1)} tokens but runs nx at {requested.group(1)}"
    )


# lib/cpu-slots.sh: GAIA_CPU_SLOTS_TIMEOUT default, in minutes. A lane that
# waits this long still runs afterwards (fail-open), so the wait is time the
# job cap has to be able to absorb on top of the work itself.
FAIL_OPEN_WAIT_MINUTES = 10


@pytest.mark.parametrize("job_name", GOVERNED_JOBS)
def test_the_job_cap_can_absorb_a_full_governor_wait(
    workflow: dict[str, Any], job_name: str
) -> None:
    """A governed lane's `timeout-minutes` must leave room for the queue.

    Enrolling a lane trades wall clock for not thrashing the box, which is the
    trade we want — but the job cap is what decides whether patience reads as a
    failure. test-typescript was enrolled at `timeout-minutes: 12` against a
    600s fail-open wait plus ~4 min of checkout, install and suite: a busy box
    would have failed it for queueing exactly as designed.
    """
    cap = workflow["jobs"][job_name]["timeout-minutes"]
    assert cap > FAIL_OPEN_WAIT_MINUTES, (
        f"{job_name}: timeout-minutes={cap} does not even cover the governor's "
        f"{FAIL_OPEN_WAIT_MINUTES}-minute fail-open wait, let alone the work after it"
    )
