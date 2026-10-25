"""runner.py's host-side subcommands: dep-marker, parallel, with-slots, spawn/join, prime-archive, cancel-superseded.

Each runs the real script; the API half talks to the local fake GitHub.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import time

from github_fake import FakeGitHub, Reply, Request, run_runner
import pytest

SHA = "a" * 40
OTHER_SHA = "b" * 40


def plain_env(**extra: str) -> dict[str, str]:
    return {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/tmp"), **extra}


# ── dep-marker ──────────────────────────────────────────────────────────────


def marker(cwd: Path, kind: str) -> str:
    proc = run_runner("dep-marker", kind, env=plain_env(), cwd=cwd)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


def test_the_node_marker_moves_with_every_input_not_just_the_lockfile(tmp_path: Path) -> None:
    (tmp_path / "pnpm-lock.yaml").write_text("lock: 1\n")
    first = marker(tmp_path, "node")
    assert first.startswith("node_modules/.gaia-installed-")
    assert marker(tmp_path, "node") == first

    (tmp_path / ".npmrc").write_text("node-linker=hoisted\n")
    assert marker(tmp_path, "node") != first


def test_an_empty_input_is_not_the_same_as_an_absent_one(tmp_path: Path) -> None:
    absent = marker(tmp_path, "python")
    (tmp_path / ".python-version").write_text("")
    assert marker(tmp_path, "python") != absent
    assert absent.startswith(".venv/.gaia-synced-")


def test_an_unknown_marker_kind_is_a_usage_error(tmp_path: Path) -> None:
    proc = run_runner("dep-marker", "ruby", env=plain_env(), cwd=tmp_path)
    assert proc.returncode == 2
    assert "node|python" in proc.stderr


# ── parallel ────────────────────────────────────────────────────────────────


def test_parallel_json_carries_every_knob() -> None:
    proc = run_runner("parallel", "--json", env=plain_env())
    assert proc.returncode == 0, proc.stderr
    doc = json.loads(proc.stdout)
    assert set(doc) == {
        "nproc",
        "mem_gb",
        "nx_parallel",
        "pytest_xdist",
        "pytest_xdist_n",
        "ruff_jobs",
        "mypy_jobs",
        "docker_jobs",
    }
    assert doc["nproc"] >= 1


def test_the_memory_guard_caps_pytest_workers() -> None:
    """A worker budget larger than the machine leaves exactly one worker, never zero."""
    proc = run_runner("parallel", "--env", env=plain_env(PYTEST_WORKER_GB="100000"))
    assert proc.returncode == 0, proc.stderr
    values = dict(line.split("=", 1) for line in proc.stdout.splitlines())
    assert values["PYTEST_XDIST_N"] == "1"
    assert values["PYTEST_XDIST"] == "1"
    assert "memory-capped" in proc.stderr


def test_an_unknown_parallel_flag_fails() -> None:
    proc = run_runner("parallel", "--gpu", env=plain_env())
    assert proc.returncode == 1


# ── with-slots ──────────────────────────────────────────────────────────────


def test_with_slots_runs_the_command_and_keeps_its_exit_code() -> None:
    proc = run_runner("with-slots", "4", "--", "bash", "-c", "echo ran; exit 7", env=plain_env())
    assert proc.returncode == 7
    assert proc.stdout.strip() == "ran"


def test_with_slots_without_a_command_is_a_usage_error() -> None:
    proc = run_runner("with-slots", "4", "--", env=plain_env())
    assert proc.returncode == 2


def test_with_slots_holds_the_tokens_in_the_shared_pool_while_running(
    tmp_path: Path, flock: str
) -> None:
    """The same pool, holder format and budget as lib/cpu-slots.sh — old and new lanes share it."""
    pool = tmp_path / "pool"
    seen = tmp_path / "seen"
    proc = run_runner(
        "with-slots",
        "3",
        "--",
        "bash",
        "-c",
        f'cat "{pool}"/holders/* > "{seen}"',
        env=plain_env(
            RUNNER_ENVIRONMENT="self-hosted", GAIA_CPU_SLOTS_DIR=str(pool), GAIA_CPU_TOKENS="8"
        ),
    )
    assert proc.returncode == 0, proc.stderr
    assert seen.read_text() == "3"
    assert list((pool / "holders").iterdir()) == []


def test_with_slots_waits_for_tokens_another_lane_holds(tmp_path: Path, flock: str) -> None:
    """A grant written by a live holder (any pid in the pool) blocks until the wait fails open."""
    pool = tmp_path / "pool"
    (pool / "holders").mkdir(parents=True)
    (pool / "holders" / f"{os.getpid()}.1").write_text("8")
    started = time.monotonic()
    proc = run_runner(
        "with-slots",
        "1",
        "--",
        "true",
        env=plain_env(
            RUNNER_ENVIRONMENT="self-hosted",
            GAIA_CPU_SLOTS_DIR=str(pool),
            GAIA_CPU_TOKENS="8",
            GAIA_CPU_SLOTS_TIMEOUT="2",
        ),
    )
    assert proc.returncode == 0
    assert time.monotonic() - started >= 2
    assert "fail-open" in proc.stderr


# ── spawn / join ────────────────────────────────────────────────────────────


def spawn(tmp_path: Path, name: str, script: str) -> None:
    started = time.monotonic()
    proc = run_runner(
        "spawn", name, "--", "bash", "-c", script, env=plain_env(RUNNER_TEMP=str(tmp_path))
    )
    assert proc.returncode == 0, proc.stderr
    assert time.monotonic() - started < 2, "spawn waited for the check instead of backgrounding it"


def join(tmp_path: Path, name: str, summary: Path) -> subprocess.CompletedProcess[str]:
    env = plain_env(RUNNER_TEMP=str(tmp_path), GITHUB_STEP_SUMMARY=str(summary))
    return run_runner("join", name, env=env)


def test_a_spawned_check_reports_its_own_log_summary_and_success_in_the_join(
    tmp_path: Path,
) -> None:
    summary = tmp_path / "step-summary"
    spawn(tmp_path, "slow", 'sleep 2; echo from-slow; echo "### slow ok" >> "$GITHUB_STEP_SUMMARY"')
    spawn(tmp_path, "fast", "echo from-fast")

    fast = join(tmp_path, "fast", summary)
    slow = join(tmp_path, "slow", summary)

    assert fast.returncode == 0, fast.stderr
    assert "from-fast" in fast.stdout and "from-slow" not in fast.stdout
    assert slow.returncode == 0, slow.stderr
    assert slow.stdout.startswith("::group::slow")
    assert "from-slow" in slow.stdout and "::error" not in slow.stdout
    assert summary.read_text() == "### slow ok\n"


def test_a_failed_check_keeps_its_exit_code_and_is_annotated(tmp_path: Path) -> None:
    spawn(tmp_path, "broken", "echo the-cause; exit 3")

    proc = join(tmp_path, "broken", tmp_path / "step-summary")

    assert proc.returncode == 3
    assert "::error title=broken::broken failed (exit 3" in proc.stdout
    assert proc.stdout.index("::endgroup::") < proc.stdout.rindex("the-cause")


def test_a_check_killed_before_it_records_an_exit_code_fails_the_join(tmp_path: Path) -> None:
    spawn(tmp_path, "killed", "sleep 30")
    pid = int((tmp_path / "bg" / "killed.pid").read_text().split()[0])
    os.killpg(pid, signal.SIGKILL)

    proc = join(tmp_path, "killed", tmp_path / "step-summary")

    assert proc.returncode == 1
    assert "exited without recording an exit code" in proc.stderr


def test_joining_a_check_that_was_never_spawned_fails_loud(tmp_path: Path) -> None:
    proc = join(tmp_path, "missing", tmp_path / "step-summary")
    assert proc.returncode == 1
    assert "was never spawned" in proc.stderr


def test_a_check_cannot_be_spawned_twice_in_one_job(tmp_path: Path) -> None:
    spawn(tmp_path, "once", "true")
    proc = run_runner("spawn", "once", "--", "true", env=plain_env(RUNNER_TEMP=str(tmp_path)))
    assert proc.returncode == 1
    assert "already started" in proc.stderr


# ── prime-archive ───────────────────────────────────────────────────────────


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    workflows = tmp_path / "repo" / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        "steps:\n"
        f"  - uses: actions/checkout@{SHA} # v7\n"
        "  - uses: owner/tool/sub/path@v2\n"
        "  - uses: ./.github/actions/local\n"
    )
    return tmp_path / "repo"


def test_prime_archive_fetches_each_pinned_action_once(
    github: FakeGitHub, checkout: Path, tmp_path: Path
) -> None:
    github.on("GET", r"/repos/owner/tool/commits/v2$", Reply(200, {"sha": OTHER_SHA}))
    github.on("GET", r"/tarball/", Reply(200, {"tar": "bytes"}))
    cache = tmp_path / "cache"
    env = github.env(GAIA_REPO=str(checkout))

    first = run_runner("prime-archive", str(cache), env=env)
    second = run_runner("prime-archive", str(cache), env=env)

    assert first.returncode == 0, first.stderr
    assert (cache / "actions_checkout" / f"{SHA}.tar.gz").is_file()
    # A nested action path resolves to its repo's tarball, keyed by the resolved commit.
    assert (cache / "owner_tool" / f"{OTHER_SHA}.tar.gz").is_file()
    assert "0 present, 2 fetched" in first.stdout
    assert "2 present, 0 fetched" in second.stdout


def test_prime_archive_warns_and_continues_past_an_unfetchable_action(
    github: FakeGitHub, checkout: Path, tmp_path: Path
) -> None:
    github.on("GET", r"/repos/owner/tool/commits/v2$", Reply(404, {"message": "Not Found"}))
    github.on("GET", r"/tarball/", Reply(200, {"tar": "bytes"}))
    proc = run_runner(
        "prime-archive", str(tmp_path / "cache"), env=github.env(GAIA_REPO=str(checkout))
    )
    assert proc.returncode == 0
    assert "::warning::could not resolve owner/tool@v2" in proc.stderr
    assert "0 present, 1 fetched" in proc.stdout


# ── cancel-superseded ───────────────────────────────────────────────────────


def superseded(github: FakeGitHub, runs: list[dict[str, object]]) -> list[str]:
    github.on("GET", r"/actions/workflows/ci.yml/runs$", Reply(200, {"workflow_runs": runs}))
    github.on("POST", r"/runs/\d+/force-cancel$", Reply(202, {}))
    github.on(
        "POST", r"/runs/10/force-cancel$", Reply(409, {"message": "Cannot cancel a completed run"})
    )
    proc = run_runner(
        "cancel-superseded",
        env=github.env(
            GITHUB_RUN_ID="100",
            GITHUB_WORKFLOW_REF="theexperiencecompany/gaia/.github/workflows/ci.yml@refs/pull/9/merge",
            GITHUB_HEAD_REF="ci/example",
            GITHUB_EVENT_NAME="pull_request",
        ),
    )
    assert proc.returncode == 0, proc.stderr
    listing = next(r for r in github.requests if r.method == "GET")
    assert listing.query["branch"] == "ci/example"
    assert listing.query["event"] == "pull_request"
    return [r.path.split("/")[-2] for r in github.requests if r.method == "POST"]


def test_only_older_active_runs_are_cancelled(github: FakeGitHub) -> None:
    cancelled = superseded(
        github,
        [
            {"id": 90, "status": "in_progress"},
            {"id": 91, "status": "queued"},
            {"id": 92, "status": "completed"},
            {"id": 100, "status": "in_progress"},
            {"id": 101, "status": "queued"},
        ],
    )
    assert cancelled == ["90", "91"]


def test_a_superseded_master_run_is_force_cancelled_so_its_always_jobs_never_run(
    github: FakeGitHub,
) -> None:
    """Regression: a plain cancel still ran the old run's always() gate and deploy plan (run 40226045729)."""
    github.on(
        "GET",
        r"/actions/workflows/ci.yml/runs$",
        Reply(200, {"workflow_runs": [{"id": 90, "status": "in_progress"}]}),
    )
    github.on("POST", r"/runs/\d+/force-cancel$", Reply(202, {}))
    proc = run_runner(
        "cancel-superseded",
        env=github.env(
            GITHUB_RUN_ID="100",
            GITHUB_WORKFLOW_REF="theexperiencecompany/gaia/.github/workflows/ci.yml@refs/heads/master",
            GITHUB_REF_NAME="master",
            GITHUB_EVENT_NAME="push",
        ),
    )
    assert proc.returncode == 0, proc.stderr
    posts = [r.path for r in github.requests if r.method == "POST"]
    assert posts == ["/repos/theexperiencecompany/gaia/actions/runs/90/force-cancel"]


def test_a_run_that_cannot_be_cancelled_is_a_warning_not_a_failure(github: FakeGitHub) -> None:
    cancelled = superseded(
        github, [{"id": 10, "status": "in_progress"}, {"id": 11, "status": "queued"}]
    )
    assert cancelled == ["10", "11"]


# ── cancel-superseded on a merge group ──────────────────────────────────────

LIVE_SHA = "c" * 40
STALE_SHA = "d" * 40
QUEUE_REF = "gh-readonly-queue/master/pr-1505-" + LIVE_SHA


def queue_reply(*live: str) -> Reply:
    nodes = [{"headCommit": {"oid": sha}} for sha in live]
    entries = {"totalCount": len(nodes), "nodes": nodes}
    return Reply(200, {"data": {"repository": {"mergeQueue": {"entries": entries}}}})


def queue_cancel(
    github: FakeGitHub, runs: list[dict[str, object]], queue: Reply
) -> subprocess.CompletedProcess[str]:
    def listing(req: Request) -> Reply:
        matching = [r for r in runs if r["status"] == req.query.get("status")]
        return Reply(200, {"workflow_runs": matching})

    github.on("GET", r"/repos/[^/]+/[^/]+/actions/runs$", responder=listing)
    github.on("POST", r"/graphql$", queue)
    github.on("POST", r"/runs/\d+/force-cancel$", Reply(202, {}))
    github.on(
        "POST", r"/runs/10/force-cancel$", Reply(409, {"message": "Cannot cancel a completed run"})
    )
    github.on("POST", r"/runs/11/force-cancel$", Reply(403, {"message": "Resource not accessible"}))
    return run_runner(
        "cancel-superseded",
        env=github.env(
            GITHUB_RUN_ID="100",
            GITHUB_WORKFLOW_REF=f"theexperiencecompany/gaia/.github/workflows/ci.yml@refs/heads/{QUEUE_REF}",
            GITHUB_REF_NAME=QUEUE_REF,
            GITHUB_EVENT_NAME="merge_group",
            MERGE_GROUP_BASE_REF="refs/heads/master",
        ),
    )


def cancelled_runs(github: FakeGitHub) -> list[str]:
    return [r.path.split("/")[-2] for r in github.requests if r.path.endswith("/force-cancel")]


def test_a_merge_group_run_whose_entry_left_the_queue_is_cancelled(github: FakeGitHub) -> None:
    runs = [
        {"id": 90, "status": "in_progress", "head_sha": STALE_SHA},
        {"id": 91, "status": "queued", "head_sha": STALE_SHA},
    ]
    proc = queue_cancel(github, runs, queue_reply(LIVE_SHA))
    assert proc.returncode == 0, proc.stderr
    assert sorted(cancelled_runs(github)) == ["90", "91"]
    listings = [r for r in github.requests if r.method == "GET"]
    assert {r.query["event"] for r in listings} == {"merge_group"}
    # Runs are read before the queue, so a group created in between is never in the listing.
    graphql = next(i for i, r in enumerate(github.requests) if r.path.endswith("/graphql"))
    assert graphql > github.requests.index(listings[-1])


def test_a_live_queue_entrys_run_is_kept(github: FakeGitHub) -> None:
    runs = [{"id": 90, "status": "queued", "head_sha": LIVE_SHA}]
    proc = queue_cancel(github, runs, queue_reply(STALE_SHA, LIVE_SHA))
    assert proc.returncode == 0, proc.stderr
    assert cancelled_runs(github) == []


def test_the_current_merge_group_run_is_never_cancelled(github: FakeGitHub) -> None:
    runs = [{"id": 100, "status": "in_progress", "head_sha": STALE_SHA}]
    proc = queue_cancel(github, runs, queue_reply(LIVE_SHA))
    assert proc.returncode == 0, proc.stderr
    assert cancelled_runs(github) == []


def test_a_stale_run_that_finished_before_its_cancel_is_done(github: FakeGitHub) -> None:
    runs = [
        {"id": 10, "status": "in_progress", "head_sha": STALE_SHA},
        {"id": 12, "status": "queued", "head_sha": STALE_SHA},
    ]
    proc = queue_cancel(github, runs, queue_reply(LIVE_SHA))
    assert proc.returncode == 0, proc.stderr
    assert sorted(cancelled_runs(github)) == ["10", "12"]


def test_a_cancel_refused_for_any_other_reason_fails_the_step(github: FakeGitHub) -> None:
    runs = [{"id": 11, "status": "in_progress", "head_sha": STALE_SHA}]
    proc = queue_cancel(github, runs, queue_reply(LIVE_SHA))
    assert proc.returncode == 1
    assert "HTTP 403" in proc.stderr


@pytest.mark.parametrize(
    "queue",
    [
        # Partial data beside errors: an empty queue read this way would cancel every run.
        Reply(
            200,
            {
                "data": {"repository": {"mergeQueue": {"entries": {"totalCount": 0, "nodes": []}}}},
                "errors": [{"message": "Resource not accessible by integration"}],
            },
        ),
        Reply(502, {"message": "Bad gateway"}),
        Reply(200, {"data": {"repository": {"mergeQueue": None}}}),
        Reply(
            200,
            {"data": {"repository": {"mergeQueue": {"entries": {"totalCount": 2, "nodes": []}}}}},
        ),
    ],
)
def test_an_unreadable_queue_cancels_nothing_and_fails(github: FakeGitHub, queue: Reply) -> None:
    runs = [{"id": 90, "status": "in_progress", "head_sha": STALE_SHA}]
    proc = queue_cancel(github, runs, queue)
    assert proc.returncode == 1
    assert "::error::" in proc.stderr
    assert cancelled_runs(github) == []
