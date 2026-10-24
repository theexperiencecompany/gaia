"""runner.py requeue-stranded decisions, driven through a local fake GitHub.

"Re-run failed jobs" re-runs only the failed lanes, so they keep the home
runs-on select chose the first time. With the home listeners offline they
queue forever. The sweep must cancel and fully re-run exactly those attempts,
leave every other run alone — and never cancel one without re-running it,
because a cancelled run is completed and no later sweep will see it again.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import subprocess

from github_fake import FakeGitHub, Reply, Request, ago, run_runner, runner

HOME = ["self-hosted", "gaia-home"]
RUN = r"/actions/runs/77$"


def queued_job(name: str, labels: list[str], queued_for: int) -> dict[str, object]:
    return {"name": name, "status": "queued", "labels": labels, "created_at": ago(queued_for)}


@dataclass
class Scenario:
    """What the fake GitHub reports for one sweep."""

    jobs: list[dict[str, object]]
    run_attempt: int = 2
    runners: list[dict[str, object]] = field(
        default_factory=lambda: [runner("home-1", "offline", "gaia-home")]
    )
    runners_reply: Reply | None = None
    # Which POST makes the run report `completed`: a cancel that lands, or only
    # the force-cancel, or nothing at all.
    completes_after: str = "cancel"
    rerun_replies: tuple[Reply, ...] = (Reply(201, {}),)


def sweep(github: FakeGitHub, scenario: Scenario) -> subprocess.CompletedProcess[str]:
    runs = {"workflow_runs": [{"id": 77, "run_attempt": scenario.run_attempt}]}
    github.on("GET", r"/actions/runs$", Reply(200, {"workflow_runs": []}))
    github.on("GET", r"/actions/runs$", Reply(200, runs), query={"status": "queued"})
    github.on("GET", r"/actions/runs/77/jobs$", Reply(200, {"jobs": scenario.jobs}))
    github.on(
        "GET",
        r"/actions/runners$",
        scenario.runners_reply or Reply(200, {"runners": scenario.runners}),
    )

    def run_status(_: Request) -> Reply:
        done = scenario.completes_after in github.posts()
        return Reply(200, {"status": "completed" if done else "in_progress"})

    github.on("GET", RUN, responder=run_status)
    github.on("POST", r"/cancel$", Reply(202, {}))
    github.on("POST", r"/force-cancel$", Reply(202, {}))
    github.on("POST", r"/rerun$", *scenario.rerun_replies)
    return run_runner(
        "requeue-stranded",
        env=github.env(QUEUE_LIMIT_SECS="480", CANCEL_WAIT_SECS="0", POLL_SECS="0"),
    )


def test_a_stranded_rerun_is_cancelled_then_rerun_in_full(github: FakeGitHub) -> None:
    proc = sweep(github, Scenario(jobs=[queued_job("docker-image", HOME, 900)]))

    assert github.posts() == ["cancel", "rerun"], proc.stdout + proc.stderr
    assert proc.returncode == 0


def test_an_online_home_runner_means_nothing_is_stranded(github: FakeGitHub) -> None:
    proc = sweep(
        github,
        Scenario(
            jobs=[queued_job("docker-image", HOME, 900)],
            runners=[runner("home-1", "online", "gaia-home")],
        ),
    )

    assert github.posts() == []
    assert proc.returncode == 0


def test_an_unknown_runner_probe_touches_nothing(github: FakeGitHub) -> None:
    proc = sweep(
        github,
        Scenario(
            jobs=[queued_job("docker-image", HOME, 900)],
            runners_reply=Reply(403, {"message": "Resource not accessible by integration"}),
        ),
    )

    assert github.posts() == []
    assert proc.returncode == 0


def test_a_first_attempt_is_left_to_its_own_watchdog(github: FakeGitHub) -> None:
    sweep(github, Scenario(jobs=[queued_job("docker-image", HOME, 900)], run_attempt=1))

    assert github.posts() == []


def test_a_lane_queued_on_github_hosted_is_not_stranded(github: FakeGitHub) -> None:
    sweep(github, Scenario(jobs=[queued_job("lint", ["ubuntu-latest"], 900)]))

    assert github.posts() == []


def test_a_lane_inside_the_queue_limit_is_left_alone(github: FakeGitHub) -> None:
    sweep(github, Scenario(jobs=[queued_job("docker-image", HOME, 60)]))

    assert github.posts() == []


def test_a_cancel_that_does_not_land_is_forced_then_rerun(github: FakeGitHub) -> None:
    """GitHub refuses to re-run an incomplete run; giving up there stranded it as cancelled."""
    proc = sweep(
        github,
        Scenario(jobs=[queued_job("docker-image", HOME, 900)], completes_after="force-cancel"),
    )

    assert github.posts() == ["cancel", "force-cancel", "rerun"], proc.stdout + proc.stderr
    assert proc.returncode == 0


def test_a_run_that_never_completes_fails_loud_without_a_rerun(github: FakeGitHub) -> None:
    proc = sweep(
        github, Scenario(jobs=[queued_job("docker-image", HOME, 900)], completes_after="never")
    )

    assert github.posts() == ["cancel", "force-cancel"]
    assert proc.returncode == 1
    assert "::error::" in proc.stdout


def test_a_transient_502_on_the_rerun_still_reruns(github: FakeGitHub) -> None:
    """The run was already cancelled: dying on one 502 here left it cancelled for good."""
    proc = sweep(
        github,
        Scenario(
            jobs=[queued_job("docker-image", HOME, 900)],
            rerun_replies=(Reply(502, {"message": "Bad Gateway"}), Reply(201, {})),
        ),
    )

    assert github.posts() == ["cancel", "rerun", "rerun"], proc.stdout + proc.stderr
    assert proc.returncode == 0
