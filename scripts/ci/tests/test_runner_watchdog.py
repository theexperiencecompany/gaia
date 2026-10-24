"""runner.py watchdog decisions, driven through a local fake GitHub.

The watchdog unparks a run whose home box died after select chose it. It once
exited on the first empty job list (lanes with unmet needs have no record
yet), cancelled runs select deliberately queued on a busy box, and died on one
transient API error, leaving the run parked with nothing watching it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import itertools
import subprocess

from github_fake import FakeGitHub, Reply, Request, ago, run_runner, runner
import pytest

WATCHDOG = "watchdog"
RUN = r"/actions/runs/1$"
JOBS = r"/actions/runs/1/jobs$"
RUNNERS = r"/actions/runners$"


def job(
    name: str, status: str, created: str, started: str = "", completed: str = ""
) -> dict[str, object]:
    return {
        "name": name,
        "status": status,
        "created_at": created,
        "started_at": started or None,
        "completed_at": completed or None,
    }


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
            RUNNER_LABEL="gaia-home",
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
    # select's online-busy-queued branch parks lanes on a busy box on purpose.
    proc = run_watchdog(
        github,
        Scenario(
            jobs=[job("build", "queued", ago(900))],
            runners=[runner("home-1", "online", "gaia-home", busy=True)],
        ),
    )
    assert github.posts() == []
    assert "the box is busy, not dead" in proc.stderr
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


def test_age_runs_from_eligibility_not_creation(github: FakeGitHub) -> None:
    # `detect` finished 30 s ago, so `build` has only just become eligible.
    proc = run_watchdog(
        github,
        Scenario(
            jobs=[
                job("detect", "completed", ago(900), started=ago(880), completed=ago(30)),
                job("build", "queued", ago(900)),
            ],
            runners=OFFLINE,
        ),
    )
    assert github.posts() == []
    assert proc.returncode == 0
    assert "eligible for 3" in proc.stdout  # ~30s, not ~900s


def test_all_lanes_picked_up_exits_clean(github: FakeGitHub) -> None:
    proc = run_watchdog(
        github, Scenario(jobs=[job("build", "in_progress", ago(100), started=ago(90))])
    )
    assert "every lane was picked up" in proc.stdout
    assert github.posts() == []
    assert proc.returncode == 0


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
