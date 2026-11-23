"""runner.py watchdog decisions, driven through a local fake GitHub.

The watchdog unparks a run whose home box died after select chose it. It once
exited on the first empty job list (lanes with unmet needs have no record
yet), cancelled runs select deliberately queued on a busy box, and died on one
transient API error, leaving the run parked with nothing watching it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import itertools
from pathlib import Path
import subprocess

from github_fake import FakeGitHub, Reply, Request, ago, run_runner, runner
import pytest
import runner as runner_mod
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]

WATCHDOG = "watchdog"
RUN = r"/actions/runs/1$"
JOBS = r"/actions/runs/1/jobs$"
RUNNERS = r"/actions/runners$"
HOME = ["self-hosted", "gaia-home"]
M4 = ["self-hosted", "gaia-m4"]
HOSTED = ["ubuntu-24.04"]


def job(
    name: str,
    status: str,
    created: str,
    started: str = "",
    completed: str = "",
    labels: list[str] | None = None,
) -> dict[str, object]:
    return {
        "name": name,
        "status": status,
        "labels": HOME if labels is None else labels,
        "created_at": created,
        "started_at": started or None,
        "completed_at": completed or None,
    }


def detect_done() -> dict[str, object]:
    return job("detect", "completed", ago(1200), ago(1190), ago(1000), labels=HOSTED)


@dataclass
class Scenario:
    """What the fake GitHub reports for one watchdog run."""

    jobs: list[dict[str, object]]
    run_status: str = "in_progress"
    runners: list[dict[str, object]] = field(default_factory=list)
    runners_reply: Reply | None = None  # overrides `runners`: an error, or a malformed body
    limit: int = 480
    # After this many polls the run reports completed, so a watchdog that
    # correctly keeps polling still terminates instead of hanging.
    polls_before_exit: int = 1
    event_name: str = "pull_request"
    dispatch_status: int = 204
    # An endpoint (RUN or JOBS) whose first answer is a 502.
    flaky: str = ""


def run_watchdog(github: FakeGitHub, scenario: Scenario) -> subprocess.CompletedProcess[str]:
    """Run the watchdog against the canned API answers in the scenario."""
    calls = itertools.count(1)
    polls = itertools.count(1)
    bad_gateway = Reply(502, {"message": "Bad Gateway"})

    def run_status(_: Request) -> Reply:
        if scenario.flaky == RUN and next(calls) == 1:
            return bad_gateway
        done = next(polls) > scenario.polls_before_exit
        return Reply(200, {"status": "completed" if done else scenario.run_status})

    jobs = Reply(200, {"jobs": [job(WATCHDOG, "in_progress", ago(5)), *scenario.jobs]})
    github.on("GET", RUN, responder=run_status)
    github.on("GET", JOBS, *([bad_gateway, jobs] if scenario.flaky == JOBS else [jobs]))
    github.on("GET", RUNNERS, scenario.runners_reply or Reply(200, {"runners": scenario.runners}))
    github.on("POST", r"/cancel$", Reply(202, {}))
    github.on("POST", r"/dispatches$", Reply(scenario.dispatch_status))
    return run_runner(
        "watchdog",
        env=github.env(
            GITHUB_RUN_ID="1",
            WATCHDOG_JOB_NAME=WATCHDOG,
            QUEUE_LIMIT_SECS=str(scenario.limit),
            POLL_SECS="0",
            GITHUB_EVENT_NAME=scenario.event_name,
            GITHUB_HEAD_REF="ci/example",
            DEFAULT_BRANCH="master",
            GITHUB_WORKFLOW_REF="theexperiencecompany/gaia/.github/workflows/ci.yml@refs/heads/ci/example",
        ),
        timeout=90,
    )


OFFLINE = [runner("home-1", "offline", "gaia-home")]


def test_no_jobs_yet_keeps_watching(github: FakeGitHub) -> None:
    # Only the watchdog's own record exists: the lanes' `needs:` have not resolved.
    proc = run_watchdog(github, Scenario(jobs=[], polls_before_exit=2))
    assert "no lanes created yet" in proc.stdout
    assert "every lane was picked up" not in proc.stdout
    assert "cancel" not in github.posts()
    assert proc.returncode == 0


def test_dead_box_is_redispatched_onto_github(github: FakeGitHub) -> None:
    # A cancelled run leaves the PR with no verdict; re-dispatch the same
    # workflow on the same head with force_github, then cancel this one.
    proc = run_watchdog(github, Scenario(jobs=[job("build", "queued", ago(900))], runners=OFFLINE))
    assert github.posts() == ["dispatches", "cancel"], proc.stderr
    dispatch = next(r for r in github.requests if r.path.endswith("/dispatches"))
    assert dispatch.path.endswith("/actions/workflows/ci.yml/dispatches")
    assert dispatch.body == {"ref": "ci/example", "inputs": {"force_github": "true"}}
    assert proc.returncode == 0


def test_stranded_merge_group_run_is_handed_to_requeue_for_a_rerun(github: FakeGitHub) -> None:
    # A dispatch on the gh-readonly-queue ref reports to no merge-group check
    # suite; only a re-run of this run does, and a run cannot re-run itself.
    proc = run_watchdog(
        github,
        Scenario(
            jobs=[job("build", "queued", ago(900))], runners=OFFLINE, event_name="merge_group"
        ),
    )
    assert github.posts() == ["dispatches"], proc.stdout + proc.stderr
    dispatch = next(r for r in github.requests if r.path.endswith("/dispatches"))
    assert dispatch.path.endswith("/actions/workflows/ci-requeue.yml/dispatches")
    assert dispatch.body == {"ref": "master", "inputs": {"run_id": "1"}}
    assert proc.returncode == 0


def test_redispatched_run_does_not_loop(github: FakeGitHub) -> None:
    # The fallback run is already on GitHub; if IT stalls, cancel rather than dispatch again.
    proc = run_watchdog(
        github,
        Scenario(
            jobs=[job("build", "queued", ago(900))], runners=OFFLINE, event_name="workflow_dispatch"
        ),
    )
    assert github.posts() == ["cancel"]
    assert proc.returncode == 1


def test_dispatch_failure_falls_back_to_cancel(github: FakeGitHub) -> None:
    proc = run_watchdog(
        github,
        Scenario(jobs=[job("build", "queued", ago(900))], runners=OFFLINE, dispatch_status=422),
    )
    assert github.posts() == ["dispatches", "cancel"]
    assert "could not re-dispatch" in proc.stdout
    assert proc.returncode == 1


def test_busy_box_is_not_cancelled(github: FakeGitHub) -> None:
    # select overflows only to an idle box, but other runs can fill it before pickup.
    proc = run_watchdog(
        github,
        Scenario(
            jobs=[job("build", "queued", ago(900))],
            runners=[runner("home-1", "online", "gaia-home", busy=True)],
        ),
    )
    assert github.posts() == []
    assert "the machine is busy, not dead" in proc.stderr
    assert proc.returncode == 0


def test_unreadable_runners_api_never_cancels(github: FakeGitHub) -> None:
    proc = run_watchdog(
        github,
        Scenario(
            jobs=[job("build", "queued", ago(900))],
            runners_reply=Reply(403, {"message": "Resource not accessible by integration"}),
        ),
    )
    assert github.posts() == []
    assert "not cancelling on an unknown" in proc.stderr
    assert proc.returncode == 0


def test_a_runners_body_without_runners_is_unknown_not_offline(github: FakeGitHub) -> None:
    """An error body read as an empty list is how a 20/20-busy box once got cancelled."""
    proc = run_watchdog(
        github,
        Scenario(
            jobs=[job("build", "queued", ago(900))],
            runners_reply=Reply(200, {"message": "Resource not accessible by integration"}),
        ),
    )
    assert github.posts() == []
    assert "not cancelling on an unknown" in proc.stderr


def test_a_lane_created_inside_the_limit_is_left_waiting(github: FakeGitHub) -> None:
    # GitHub creates a job when its needs resolve (run 45103036609: every slice's
    # created_at is detect's completed_at), so its own creation is its eligibility.
    proc = run_watchdog(
        github, Scenario(jobs=[detect_done(), job("build", "queued", ago(30))], runners=OFFLINE)
    )
    assert github.posts() == []
    assert proc.returncode == 0
    assert "eligible for 3" in proc.stdout  # ~30s


def progressing_hosted_jobs() -> list[dict[str, object]]:
    """GitHub-hosted lanes of the same run that keep starting and finishing beside a parked slice."""
    return [
        detect_done(),
        job("lint-node", "completed", ago(600), started=ago(590), completed=ago(5), labels=HOSTED),
        job("mutation (shard 1/2)", "in_progress", ago(600), started=ago(10), labels=HOSTED),
    ]


def test_a_slice_parked_on_a_dead_label_is_caught_while_hosted_lanes_progress(
    github: FakeGitHub,
) -> None:
    """Every hosted start or finish reset the clock, so the parked slice never aged past the limit."""
    slice_job = job("test-python (unit-a)", "queued", ago(600))
    proc = run_watchdog(
        github, Scenario(jobs=[*progressing_hosted_jobs(), slice_job], runners=OFFLINE)
    )
    assert github.posts() == ["dispatches", "cancel"], proc.stdout + proc.stderr


def test_a_merge_group_parked_on_a_dead_label_is_handed_to_requeue(github: FakeGitHub) -> None:
    slice_job = job("test-python (integration)", "queued", ago(600))
    proc = run_watchdog(
        github,
        Scenario(
            jobs=[*progressing_hosted_jobs(), slice_job], runners=OFFLINE, event_name="merge_group"
        ),
    )
    assert github.posts() == ["dispatches"], proc.stdout + proc.stderr
    dispatch = next(r for r in github.requests if r.path.endswith("/dispatches"))
    assert dispatch.path.endswith("/actions/workflows/ci-requeue.yml/dispatches")


def test_a_busy_box_beside_progressing_hosted_lanes_is_not_cancelled(github: FakeGitHub) -> None:
    slice_job = job("test-python (unit-a)", "queued", ago(600))
    busy = [runner("home-1", "online", "gaia-home", busy=True)]
    proc = run_watchdog(
        github, Scenario(jobs=[*progressing_hosted_jobs(), slice_job], runners=busy)
    )
    assert github.posts() == []
    assert "the machine is busy, not dead" in proc.stderr


def test_the_watchdog_outlives_its_queue_limit() -> None:
    """It starts when detect has created the slices; 15 min from select once ended 1 s past the limit."""
    workflow = yaml.safe_load((REPO_ROOT / ".github/workflows/ci.yml").read_text())
    watchdog = workflow["jobs"]["runner-watchdog"]
    assert "detect" in watchdog["needs"]
    budget = (
        runner_mod.QUEUE_LIMIT_SECS
        + runner_mod.WATCHDOG_POLL_SECS
        + runner_mod.WATCHDOG_MARGIN_SECS
    )
    assert watchdog["timeout-minutes"] * 60 >= budget
    assert "QUEUE_LIMIT_SECS" not in str(watchdog), "the limit has one owner: runner.py"


def test_all_lanes_picked_up_exits_clean(github: FakeGitHub) -> None:
    proc = run_watchdog(
        github,
        Scenario(jobs=[detect_done(), job("build", "in_progress", ago(100), started=ago(90))]),
    )
    assert "every self-hosted lane was picked up" in proc.stdout
    assert github.posts() == []
    assert proc.returncode == 0


def test_a_lane_queued_on_github_hosted_is_not_a_dead_box(github: FakeGitHub) -> None:
    proc = run_watchdog(
        github,
        Scenario(
            jobs=[detect_done(), job("lint", "queued", ago(900), labels=HOSTED)], runners=OFFLINE
        ),
    )
    assert github.posts() == []
    assert proc.returncode == 0


def test_a_stalled_lane_is_judged_by_its_own_machine(github: FakeGitHub) -> None:
    """A unit slice parked on a dead M4 is stranded even while the box is up."""
    proc = run_watchdog(
        github,
        Scenario(
            jobs=[detect_done(), job("test-python (unit-a)", "queued", ago(900), labels=M4)],
            runners=[runner("home-1", "online", "gaia-home"), runner("m4-1", "offline", "gaia-m4")],
        ),
    )
    assert github.posts() == ["dispatches", "cancel"], proc.stdout + proc.stderr


def test_a_machine_listed_offline_while_this_run_uses_it_is_not_dead(github: FakeGitHub) -> None:
    """The runners API once listed all 22 listeners offline while they ran jobs."""
    proc = run_watchdog(
        github,
        Scenario(
            jobs=[
                detect_done(),
                job("test-python (unit-a)", "in_progress", ago(900), started=ago(600)),
                job("test-python (integration)", "queued", ago(900)),
            ],
            runners=OFFLINE,
        ),
    )
    assert github.posts() == []
    assert "in progress on it" in proc.stderr


@pytest.mark.parametrize("terminal", ["completed", "cancelled", "failure"])
def test_finished_run_stops_watching(github: FakeGitHub, terminal: str) -> None:
    proc = run_watchdog(
        github,
        Scenario(run_status=terminal, jobs=[job("build", "queued", ago(900))], polls_before_exit=0),
    )
    assert "nothing left to watch" in proc.stdout
    assert github.posts() == []
    assert proc.returncode == 0


@pytest.mark.parametrize("endpoint", [RUN, JOBS])
def test_a_transient_502_is_retried_instead_of_killing_the_watch(
    github: FakeGitHub, endpoint: str
) -> None:
    """One 502 used to exit the watchdog, leaving a parked run with nothing watching it."""
    proc = run_watchdog(
        github, Scenario(jobs=[job("build", "queued", ago(900))], runners=OFFLINE, flaky=endpoint)
    )
    assert github.posts() == ["dispatches", "cancel"], proc.stdout + proc.stderr
    assert proc.returncode == 0
