"""runner.py requeue-stranded decisions, driven through a local fake GitHub.

"Re-run failed jobs" re-runs only the failed lanes, so they keep the home
runs-on select chose the first time. With the home listeners offline they
queue forever. The sweep must cancel and fully re-run exactly those attempts,
leave every other run alone — and never cancel one without re-running it,
because a cancelled run is completed and no later sweep will see it again.

The cancel is always a force-cancel. A plain cancel still runs every
`if: always()` job, so quality-gate concludes failure on the stranded attempt —
the conclusion that removes a merge group from the queue. A force-cancelled
attempt runs no further job (observed on GitHub, run 40057428378 attempt 2),
so the gate reports nothing until the re-run's own gate does.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import subprocess

from github_fake import FakeGitHub, Reply, Request, ago, run_runner, runner
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]

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
    # Which POST makes the run report `completed`: the force-cancel, or nothing at all.
    completes_after: str = "force-cancel"
    rerun_replies: tuple[Reply, ...] = (Reply(201, {}),)
    # REQUEUE_RUN_ID: the one run a watchdog handed over, instead of a sweep.
    target: str = ""


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
        env=github.env(
            QUEUE_LIMIT_SECS="480",
            CANCEL_WAIT_SECS="0",
            POLL_SECS="0",
            REQUEUE_RUN_ID=scenario.target,
        ),
    )


def test_a_stranded_rerun_is_force_cancelled_then_rerun_in_full(github: FakeGitHub) -> None:
    proc = sweep(github, Scenario(jobs=[queued_job("docker-image", HOME, 900)]))

    assert github.posts() == ["force-cancel", "rerun"], proc.stdout + proc.stderr
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


def test_an_unknown_runner_probe_touches_nothing_and_fails(github: FakeGitHub) -> None:
    """A sweep that cannot see the runners cannot do its job; green hid a 403 on every sweep."""
    proc = sweep(
        github,
        Scenario(
            jobs=[queued_job("docker-image", HOME, 900)],
            runners_reply=Reply(403, {"message": "Resource not accessible by integration"}),
        ),
    )

    assert github.posts() == []
    assert proc.returncode != 0


def test_the_sweep_runs_with_the_token_that_can_list_runners() -> None:
    """github.token cannot list self-hosted runners, so every probe came back 403."""
    workflow = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "ci-requeue.yml").read_text())
    (step,) = [s for s in workflow["jobs"]["requeue"]["steps"] if "run" in s]
    assert "secrets.HOMELAB_GH_PAT" in step["env"]["GITHUB_TOKEN"]


def test_a_first_attempt_is_left_to_its_own_watchdog(github: FakeGitHub) -> None:
    sweep(github, Scenario(jobs=[queued_job("docker-image", HOME, 900)], run_attempt=1))

    assert github.posts() == []


def test_a_handed_over_first_attempt_is_rerun_in_full(github: FakeGitHub) -> None:
    # The merge_group watchdog cannot re-run its own run; it names it here.
    proc = sweep(
        github, Scenario(jobs=[queued_job("docker-image", HOME, 900)], run_attempt=1, target="77")
    )

    # Never a plain cancel: it would run quality-gate red and drop the merge group.
    assert github.posts() == ["force-cancel", "rerun"], proc.stdout + proc.stderr
    assert not any(r.path.endswith("/actions/runs") for r in github.requests)
    assert proc.returncode == 0


def test_a_lane_queued_on_github_hosted_is_not_stranded(github: FakeGitHub) -> None:
    sweep(github, Scenario(jobs=[queued_job("lint", ["ubuntu-latest"], 900)]))

    assert github.posts() == []


def test_a_lane_inside_the_queue_limit_is_left_alone(github: FakeGitHub) -> None:
    sweep(github, Scenario(jobs=[queued_job("docker-image", HOME, 60)]))

    assert github.posts() == []


def test_a_run_that_never_completes_fails_loud_without_a_rerun(github: FakeGitHub) -> None:
    proc = sweep(
        github, Scenario(jobs=[queued_job("docker-image", HOME, 900)], completes_after="never")
    )

    # GitHub refuses to re-run an incomplete run, so nothing is re-run on top of it.
    assert github.posts() == ["force-cancel"]
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

    assert github.posts() == ["force-cancel", "rerun", "rerun"], proc.stdout + proc.stderr
    assert proc.returncode == 0


# --- rescope ------------------------------------------------------------------
#
# A retarget fires only `edited`, which ci.yml no longer runs on (its run
# replaced every job row with "Skipped"). pr-title.yml re-runs the head's latest
# pull_request run instead, so the lanes re-scope to the new base.

HEAD = "c9d667254c9d667254c9d667254c9d667254c9d6"


def rescope(
    github: FakeGitHub, runs: list[dict[str, object]], completes_after: str = "force-cancel"
) -> subprocess.CompletedProcess[str]:
    github.on("GET", r"/actions/workflows/ci\.yml/runs$", Reply(200, {"workflow_runs": runs}))

    def run_status(_: Request) -> Reply:
        done = completes_after in github.posts()
        return Reply(200, {"status": "completed" if done else "in_progress"})

    github.on("GET", RUN, responder=run_status)
    github.on("POST", r"/force-cancel$", Reply(202, {}))
    github.on("POST", r"/rerun$", Reply(201, {}))
    return run_runner(
        "rescope", "ci.yml", env=github.env(HEAD_SHA=HEAD, CANCEL_WAIT_SECS="0", POLL_SECS="0")
    )


def test_a_retarget_reruns_the_heads_completed_pr_run(github: FakeGitHub) -> None:
    proc = rescope(github, [{"id": 77, "status": "completed"}])

    assert github.posts() == ["rerun"], proc.stdout + proc.stderr
    assert proc.returncode == 0
    (listing,) = [r for r in github.requests if r.path.endswith("/ci.yml/runs")]
    assert listing.query["head_sha"] == HEAD
    assert listing.query["event"] == "pull_request"


def test_a_run_still_going_is_force_cancelled_then_rerun(github: FakeGitHub) -> None:
    # It may have resolved the old base already. Never a plain cancel: that runs
    # quality-gate red on the way out.
    proc = rescope(github, [{"id": 77, "status": "in_progress"}])

    assert github.posts() == ["force-cancel", "rerun"], proc.stdout + proc.stderr
    assert proc.returncode == 0


def test_a_run_that_never_completes_after_the_cancel_fails_loud(github: FakeGitHub) -> None:
    proc = rescope(github, [{"id": 77, "status": "in_progress"}], completes_after="never")

    assert github.posts() == ["force-cancel"]
    assert proc.returncode == 1
    assert "::error::" in proc.stdout


def test_no_run_yet_touches_nothing(github: FakeGitHub) -> None:
    proc = rescope(github, [])

    assert github.posts() == []
    assert proc.returncode == 0
