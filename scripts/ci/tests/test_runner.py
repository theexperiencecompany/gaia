"""runner.py select: trust gates and run-ordered routing, against a local fake GitHub.

Every trust gate is decided before any API call, so a gate that leaks shows up
as a request to the fake server. Routing reads this repo's active ci.yml runs
and places each run by the runs ahead of it: the first stays GitHub-hosted, the
later ones move their test slices to the box (4 slots) and the M4 (2 slots,
unit slices only), and Blacksmith is the paid last resort once GitHub is
saturated and no self-hosted slot is free. Runs that start together read the
same list, so they get distinct answers instead of all reading an empty queue.
"""

from __future__ import annotations

from collections import Counter
import json
import os
from pathlib import Path
import re
import subprocess

from github_fake import REPO, RUNNER, FakeGitHub, Reply, ago, run_runner, runner
import pytest
import runner as runner_mod

HOSTED = runner_mod.DEFAULT_FALLBACK
BOX_LABEL = "gaia-home"
M4_LABEL = "gaia-m4"
BOX = '["self-hosted","gaia-home"]'
M4 = '["self-hosted","gaia-m4"]'
BLACKSMITH = "blacksmith-4vcpu-ubuntu-2404"
WORKFLOW_RUNS = r"/actions/workflows/ci\.yml/runs$"
RUNNERS = r"/actions/runners$"
POOLS = ("general", "unit", "services")
SLICES = json.loads((RUNNER.parent / "lib" / "test-slices.json").read_text())["slices"]


def ci_run(
    run_id: int,
    event: str = "pull_request",
    *,
    branch: str = "",
    started: str = "2026-11-23T10:00:00Z",
) -> dict[str, object]:
    return {
        "id": run_id,
        "event": event,
        "status": "in_progress",
        "head_branch": branch or f"feature-{run_id}",
        "run_started_at": started,
        "created_at": started,
        "run_attempt": 1,
        "head_repository": {"full_name": REPO},
        "triggering_actor": {"login": "agent"},
    }


def ci_job(name: str, status: str, labels: list[str]) -> dict[str, object]:
    return {
        "name": name,
        "status": status,
        "labels": labels,
        "started_at": None if status == "queued" else ago(60),
    }


def jobs(github: FakeGitHub, run_id: int, *listed: dict[str, object]) -> None:
    github.on("GET", rf"/actions/runs/{run_id}/jobs$", Reply(200, {"jobs": list(listed)}))


def active(github: FakeGitHub, *runs: dict[str, object]) -> None:
    """Serve the runs as this repo's in-progress ci.yml runs, each still in select-runner."""
    github.on("GET", WORKFLOW_RUNS, Reply(200, {"workflow_runs": []}), query={"status": "queued"})
    github.on(
        "GET",
        WORKFLOW_RUNS,
        Reply(200, {"workflow_runs": list(runs)}),
        query={"status": "in_progress"},
    )
    for run in runs:
        jobs(github, int(str(run["id"])), ci_job("select-runner", "in_progress", [BLACKSMITH]))


def listeners(github: FakeGitHub, *, box: int = 10, m4: int = runner_mod.M4_SLOTS) -> None:
    pool = [runner(f"gaia-home-{i}", "online", BOX_LABEL) for i in range(box)]
    pool += [runner(f"gaia-m4-{i}", "online", M4_LABEL) for i in range(m4)]
    github.on("GET", RUNNERS, Reply(200, {"runners": pool}))


def run_select(
    github: FakeGitHub, run_id: int, event: str = "pull_request", **env: str
) -> subprocess.CompletedProcess[str]:
    is_pr = event == "pull_request"
    return run_runner(
        "select",
        env=github.env(
            **{
                "PR_HEAD_REPO": REPO if is_pr else "",
                "PR_AUTHOR_ASSOCIATION": "MEMBER" if is_pr else "",
                "GITHUB_RUN_ID": str(run_id),
                "GITHUB_EVENT_NAME": event,
                "GITHUB_WORKFLOW_REF": f"{REPO}/.github/workflows/ci.yml@refs/heads/feature",
                "M4_LABEL": M4_LABEL,
                **env,
            }
        ),
    )


def outputs(proc: subprocess.CompletedProcess[str]) -> dict[str, str]:
    assert proc.returncode == 0, proc.stderr
    return dict(line.split("=", 1) for line in proc.stdout.splitlines() if "=" in line)


def select(
    github: FakeGitHub, run_id: int = 1, event: str = "pull_request", **env: str
) -> dict[str, str]:
    return outputs(run_select(github, run_id, event, **env))


def slice_count(tier: str, pool: str) -> int:
    return sum(1 for s in SLICES if s["pool"] == pool and (tier == "full" or s["tier"] == "fast"))


def self_hosted_load(choices: list[dict[str, str]], tier: str) -> Counter[str]:
    """Count the jobs a set of runs' choices put on each self-hosted label."""
    load: Counter[str] = Counter()
    for out in choices:
        for pool in ("unit", "services"):
            if out[pool] in (BOX, M4):
                load[json.loads(out[pool])[1]] += slice_count(tier, pool)
    return load


# ── trust gates: decided before any probe ───────────────────────────────────


@pytest.mark.parametrize(
    "association", ["COLLABORATOR", "CONTRIBUTOR", "FIRST_TIME_CONTRIBUTOR", "FIRST_TIMER", "NONE"]
)
def test_non_member_pr_never_reaches_the_box(github: FakeGitHub, association: str) -> None:
    out = select(github, PR_AUTHOR_ASSOCIATION=association)
    assert out["is_self_hosted"] == "false"
    assert all(out[pool] == HOSTED for pool in POOLS)
    assert github.requests == []


def test_fork_pr_stays_hosted_without_an_api_call(github: FakeGitHub) -> None:
    out = select(github, PR_HEAD_REPO="outsider/gaia")
    assert all(out[pool] == HOSTED for pool in POOLS)
    assert github.requests == []


@pytest.mark.parametrize("actor", ["dependabot[bot]", "github-actions[bot]", "renovate[bot]"])
def test_bot_actor_never_reaches_the_box(github: FakeGitHub, actor: str) -> None:
    out = select(github, GITHUB_ACTOR=actor)
    assert all(out[pool] == HOSTED for pool in POOLS)
    assert github.requests == []


def test_forced_github_skips_every_probe(github: FakeGitHub) -> None:
    out = select(github, FORCE_GITHUB="true")
    assert all(out[pool] == HOSTED for pool in POOLS)
    assert github.requests == []


# ── run-ordered routing ─────────────────────────────────────────────────────


def test_a_lone_run_stays_hosted_and_reads_only_the_run_list(github: FakeGitHub) -> None:
    active(github, ci_run(1))
    listeners(github)
    out = select(github, 1)
    assert all(out[pool] == HOSTED for pool in POOLS)
    assert out["is_self_hosted"] == "false"
    assert [r.path for r in github.requests] == [f"/repos/{REPO}/actions/workflows/ci.yml/runs"] * 2


def test_simultaneous_pr_runs_get_distinct_places_within_every_cap(github: FakeGitHub) -> None:
    """Four pushes land together; each select sees the same four runs and none of their slices."""
    burst = [ci_run(i) for i in (11, 12, 13, 14)]
    active(github, *burst)
    listeners(github)
    choices = [select(github, int(str(run["id"]))) for run in burst]

    assert [c["unit"] for c in choices] == [HOSTED, M4, BOX, BOX]
    assert all(c["general"] == HOSTED for c in choices)
    load = self_hosted_load(choices, "fast")
    assert load[BOX_LABEL] <= runner_mod.BOX_SLOTS
    assert load[M4_LABEL] <= runner_mod.M4_SLOTS


def test_full_tier_runs_never_put_more_than_four_slices_on_the_box(github: FakeGitHub) -> None:
    groups = [ci_run(i, "merge_group") for i in (21, 22, 23)]
    active(github, *groups)
    listeners(github)
    choices = [select(github, int(str(run["id"])), "merge_group") for run in groups]

    assert choices[0]["unit"] == choices[0]["services"] == HOSTED
    assert choices[1]["unit"] == choices[1]["services"] == BOX
    assert choices[2]["unit"] == choices[2]["services"] == HOSTED
    assert self_hosted_load(choices, "full")[BOX_LABEL] == runner_mod.BOX_SLOTS


def test_the_m4_only_ever_takes_unit_slices(github: FakeGitHub) -> None:
    active(github, ci_run(31, "workflow_dispatch"), ci_run(32, "workflow_dispatch"))
    listeners(github, box=0)
    out = select(github, 32, "workflow_dispatch")
    assert out["unit"] == M4
    assert out["services"] == out["general"] == HOSTED


def test_a_merge_group_never_lands_on_the_m4(github: FakeGitHub) -> None:
    active(github, ci_run(41), ci_run(42, "merge_group"))
    listeners(github, box=0)
    out = select(github, 42, "merge_group")
    assert out["unit"] == out["services"] == HOSTED


def test_the_m4_is_off_until_its_label_is_set(github: FakeGitHub) -> None:
    active(github, ci_run(51), ci_run(52))
    listeners(github, box=0)
    out = select(github, 52, M4_LABEL="")
    assert out["unit"] == HOSTED


def test_a_run_ahead_past_detect_is_judged_by_its_real_jobs(github: FakeGitHub) -> None:
    """The run ahead of 62 finished, so recomputing 62 would call it first in line and hosted."""
    active(github, ci_run(62), ci_run(63))
    jobs(
        github,
        62,
        ci_job("detect", "completed", [runner_mod.HOSTED_LINUX_IMAGE]),
        ci_job("test-python (unit-a)", "in_progress", ["self-hosted", BOX_LABEL]),
        ci_job("test-python (unit-b)", "in_progress", ["self-hosted", BOX_LABEL]),
        ci_job("test-python (integration)", "queued", ["self-hosted", BOX_LABEL]),
    )
    listeners(github, m4=0)
    out = select(github, 63)
    assert out["unit"] == HOSTED, "three of the box's four slots are taken and two are needed"


def test_slices_a_run_ahead_has_finished_free_their_slots(github: FakeGitHub) -> None:
    active(github, ci_run(71), ci_run(72), ci_run(73))
    jobs(
        github,
        72,
        ci_job("detect", "completed", [runner_mod.HOSTED_LINUX_IMAGE]),
        ci_job("test-python (unit-a)", "completed", ["self-hosted", BOX_LABEL]),
        ci_job("test-python (unit-b)", "completed", ["self-hosted", BOX_LABEL]),
        ci_job("mutation", "in_progress", [runner_mod.HOSTED_LINUX_IMAGE]),
    )
    listeners(github, m4=0)
    out = select(github, 73)
    assert out["unit"] == BOX


def test_a_box_listed_offline_but_running_a_job_is_alive(github: FakeGitHub) -> None:
    """The runners API once listed all 22 listeners offline while they ran jobs."""
    active(github, ci_run(81), ci_run(82), ci_run(83))
    jobs(
        github,
        82,
        ci_job("detect", "completed", [runner_mod.HOSTED_LINUX_IMAGE]),
        ci_job("test-python (unit-a)", "in_progress", ["self-hosted", BOX_LABEL]),
        ci_job("test-python (unit-b)", "completed", ["self-hosted", BOX_LABEL]),
    )
    offline = [runner(f"gaia-home-{i}", "offline", BOX_LABEL) for i in range(10)]
    github.on("GET", RUNNERS, Reply(200, {"runners": offline}))
    out = select(github, 83, M4_LABEL="")
    assert out["unit"] == BOX


def test_an_offline_box_with_no_running_job_takes_nothing(github: FakeGitHub) -> None:
    active(github, ci_run(91), ci_run(92))
    offline = [runner(f"gaia-home-{i}", "offline", BOX_LABEL) for i in range(10)]
    github.on("GET", RUNNERS, Reply(200, {"runners": offline}))
    out = select(github, 92, M4_LABEL="")
    assert out["unit"] == HOSTED
    assert out["is_self_hosted"] == "false"


def test_a_run_github_never_started_is_not_ahead(github: FakeGitHub) -> None:
    """Three runs from 11 Nov still list as queued with no job; counted, they made every run later."""
    zombie = {**ci_run(7, started="2026-11-11T20:33:51Z"), "status": "queued"}
    github.on(
        "GET", WORKFLOW_RUNS, Reply(200, {"workflow_runs": [zombie]}), query={"status": "queued"}
    )
    github.on(
        "GET",
        WORKFLOW_RUNS,
        Reply(200, {"workflow_runs": [ci_run(8, started=ago(30))]}),
        query={"status": "in_progress"},
    )
    listeners(github)
    out = select(github, 8)
    assert out["unit"] == HOSTED
    assert not any("/runs/7/jobs" in r.path for r in github.requests)


def test_a_rerun_of_an_old_run_still_queued_is_counted(github: FakeGitHub) -> None:
    """A re-run keeps its created_at; cutting on it hid every re-run until its first job started."""
    rerun = {
        **ci_run(9, started=ago(20)),
        "status": "queued",
        "created_at": "2026-11-11T20:33:51Z",
    }
    github.on(
        "GET", WORKFLOW_RUNS, Reply(200, {"workflow_runs": [rerun]}), query={"status": "queued"}
    )
    github.on(
        "GET",
        WORKFLOW_RUNS,
        Reply(200, {"workflow_runs": [ci_run(10, started=ago(10))]}),
        query={"status": "in_progress"},
    )
    jobs(github, 9, ci_job("select-runner", "queued", [BLACKSMITH]))
    listeners(github)
    out = select(github, 10)
    assert out["unit"] == M4, "the re-run is ahead, so run 10 is second in line"


def test_a_superseded_run_still_holding_box_jobs_keeps_their_slots(github: FakeGitHub) -> None:
    """Its box jobs run on while they are force-cancelled (and the listener wedges for 5 min)."""
    active(
        github,
        ci_run(190),
        ci_run(191, branch="feat"),
        ci_run(192, branch="feat"),
        ci_run(193),
    )
    jobs(
        github,
        191,
        ci_job("detect", "completed", [runner_mod.HOSTED_LINUX_IMAGE]),
        ci_job("test-python (integration)", "in_progress", ["self-hosted", BOX_LABEL]),
        ci_job("test-python (bridge)", "in_progress", ["self-hosted", BOX_LABEL]),
        ci_job("test-python (unit-a)", "in_progress", ["self-hosted", BOX_LABEL]),
    )
    listeners(github, m4=0)
    out = select(github, 193, M4_LABEL="")
    assert out["unit"] == HOSTED, "three box slots are still busy with run 191's jobs"


def test_an_m4_with_more_listeners_than_slots_is_refused(github: FakeGitHub) -> None:
    """Nothing on the M4 caps CPU per job, so every listener beyond its slots oversubscribes it."""
    active(github, ci_run(201), ci_run(202))
    listeners(github, box=0, m4=4)
    proc = run_select(github, 202)
    assert outputs(proc)["unit"] == HOSTED
    assert "gaia-m4" in proc.stderr


def test_a_superseded_run_on_the_same_branch_is_not_ahead(github: FakeGitHub) -> None:
    active(github, ci_run(101, branch="feat"), ci_run(102, branch="feat"))
    listeners(github)
    out = select(github, 102)
    assert out["unit"] == HOSTED


def test_a_rerun_queues_behind_the_runs_already_deciding(github: FakeGitHub) -> None:
    """Run 5 is old but its re-run started last: ordering by id alone put it first."""
    active(
        github,
        ci_run(5, started="2026-11-23T10:05:00Z"),
        ci_run(110, started="2026-11-23T10:01:00Z"),
    )
    listeners(github)
    out = select(github, 5)
    assert out["unit"] == M4


# ── Blacksmith: paid, the last resort, never silent ─────────────────────────


def test_one_run_ahead_and_no_free_slot_stays_hosted_not_blacksmith(github: FakeGitHub) -> None:
    active(github, ci_run(121), ci_run(122))
    listeners(github, box=0, m4=0)
    out = select(github, 122, BLACKSMITH_LABEL=BLACKSMITH)
    assert out["unit"] == HOSTED


def test_a_saturated_github_and_full_machines_go_to_blacksmith_loudly(github: FakeGitHub) -> None:
    active(github, ci_run(131), ci_run(132), ci_run(133))
    listeners(github, box=0, m4=0)
    proc = run_select(github, 133, BLACKSMITH_LABEL=BLACKSMITH)
    out = outputs(proc)
    assert out["unit"] == f'["{BLACKSMITH}"]'
    assert out["general"] == HOSTED, "Blacksmith never takes the compute lanes"
    assert re.search(r"::warning::.*Blacksmith.*paid", proc.stderr)


def test_without_a_blacksmith_label_a_saturated_run_queues_on_github(github: FakeGitHub) -> None:
    active(github, ci_run(141), ci_run(142), ci_run(143))
    listeners(github, box=0, m4=0)
    out = select(github, 143)
    assert out["unit"] == HOSTED


# ── API failures fail toward GitHub-hosted ──────────────────────────────────


def test_an_unreadable_run_list_keeps_everything_hosted(github: FakeGitHub) -> None:
    github.on("GET", WORKFLOW_RUNS, Reply(500, {"message": "Server Error"}))
    proc = run_select(github, 1, BLACKSMITH_LABEL=BLACKSMITH)
    out = outputs(proc)
    assert "::warning::" in proc.stderr
    assert all(out[pool] == HOSTED for pool in POOLS)


def test_an_unreadable_runners_list_keeps_the_slices_hosted(github: FakeGitHub) -> None:
    active(github, ci_run(151), ci_run(152))
    github.on("GET", RUNNERS, Reply(403, {"message": "Resource not accessible by integration"}))
    proc = run_select(github, 152, BLACKSMITH_LABEL=BLACKSMITH)
    assert "::warning::runners API unavailable" in proc.stderr
    assert outputs(proc)["unit"] == HOSTED


def test_an_unreadable_job_list_keeps_the_slices_hosted(github: FakeGitHub) -> None:
    active(github, ci_run(161), ci_run(162))
    github.on("GET", r"/actions/runs/161/jobs$", Reply(500, {"message": "Server Error"}))
    listeners(github)
    proc = run_select(github, 162)
    assert "::warning::" in proc.stderr
    assert outputs(proc)["unit"] == HOSTED


def test_a_runners_listing_spanning_pages_is_read_whole(github: FakeGitHub) -> None:
    """The box and the M4 have more listeners than one page holds; the box may be on page two."""
    active(github, ci_run(171), ci_run(172))
    page_two = f"{github.url}/repos/{REPO}/actions/runners?page=2"
    other = runner("lint-1", "online", "gaia-home-lint")
    github.on("GET", RUNNERS, Reply(200, {"runners": [other]}, link=f'<{page_two}>; rel="next"'))
    box = [runner(f"gaia-home-{i}", "online", BOX_LABEL) for i in range(10)]
    github.on("GET", RUNNERS, Reply(200, {"runners": box}), query={"page": "2"})
    out = select(github, 172, M4_LABEL="")
    assert out["unit"] == BOX


# ── dispatch overrides ──────────────────────────────────────────────────────


@pytest.mark.parametrize("busy", [False, True])
def test_force_home_sends_every_pool_to_an_online_box(github: FakeGitHub, busy: bool) -> None:
    github.on(
        "GET", RUNNERS, Reply(200, {"runners": [runner("h", "online", BOX_LABEL, busy=busy)]})
    )
    out = select(github, 1, "workflow_dispatch", FORCE_HOME="true")
    assert all(out[pool] == BOX for pool in POOLS)
    assert out["is_self_hosted"] == "true"


def test_force_home_dies_rather_than_fall_back(github: FakeGitHub) -> None:
    github.on("GET", RUNNERS, Reply(200, {"runners": [runner("h", "offline", BOX_LABEL)]}))
    proc = run_select(github, 1, "workflow_dispatch", FORCE_HOME="true")
    assert proc.returncode == 1
    assert "::error::" in proc.stderr
    assert "unit=" not in proc.stdout


def test_a_dispatched_box_label_replaces_the_box(github: FakeGitHub) -> None:
    active(github, ci_run(181, "workflow_dispatch"), ci_run(182, "workflow_dispatch"))
    trial = [runner(f"trial-{i}", "online", "gaia-trial") for i in range(4)]
    github.on("GET", RUNNERS, Reply(200, {"runners": trial}))
    out = select(github, 182, "workflow_dispatch", RUNNER_LABEL="gaia-trial", M4_LABEL="")
    assert out["services"] == out["unit"] == '["self-hosted","gaia-trial"]'


# ── the one pool declaration ────────────────────────────────────────────────


def test_every_slice_declares_a_pool_select_publishes() -> None:
    assert {s["pool"] for s in SLICES} <= set(POOLS)


def test_every_routed_job_reads_a_pool_select_publishes() -> None:
    """A job that names an output select does not write lands on a nameless runner."""
    workflow = (RUNNER.parent.parent.parent / ".github/workflows/ci.yml").read_text()
    asked = set(re.findall(r"needs\.select-runner\.outputs\.(\w+)", workflow))
    assert asked <= {*POOLS, "is_self_hosted"}, asked
    by_slice = (
        "needs.select-runner.outputs[fromJSON(needs.detect.outputs.slice_defs)[matrix.slice].pool]"
    )
    assert workflow.count(by_slice) == 2, (
        "test-python and test-python-engines route by the slice's pool"
    )


# ── the composite and the path references ───────────────────────────────────


def test_every_ci_script_path_in_the_workflows_resolves() -> None:
    """A rename once put the subcommand into the composite's SCRIPT path: exit 127, every lane skipped."""
    repo = RUNNER.parent.parent.parent
    pattern = re.compile(r"scripts/ci/[A-Za-z0-9_./-]+\.(?:sh|py)\b")
    missing = []
    for path in [*sorted(repo.glob(".github/**/*.yml")), repo / "mise.toml"]:
        for ref in pattern.findall(path.read_text()):
            if not (repo / ref).is_file():
                missing.append(f"{path.relative_to(repo)} -> {ref}")
    assert not missing, missing


def test_the_select_runner_composite_runs_runner_py_select() -> None:
    action = (RUNNER.parent.parent.parent / ".github/actions/select-runner/action.yml").read_text()
    assert 'SCRIPT="${{ github.action_path }}/../../../scripts/ci/runner.py"' in action
    assert 'python3 "$SCRIPT" select' in action
    for output in (*POOLS, "is_self_hosted"):
        assert f"steps.probe.outputs.{output} }}}}" in action, output


# ── heal-venv ───────────────────────────────────────────────────────────────


def heal_venv(venv: Path) -> None:
    proc = run_runner("heal-venv", str(venv), env={"PATH": os.environ["PATH"]})
    assert proc.returncode == 0, proc.stderr


def healthy_venv(venv: Path) -> None:
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "python").symlink_to(Path(os.environ.get("SHELL", "/bin/sh")).resolve())
    (venv / "pyvenv.cfg").write_text("home = /usr/bin\n")


def test_a_venv_whose_interpreter_link_dangles_is_removed(tmp_path: Path) -> None:
    venv = tmp_path / ".venv-voice-agent"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "python").symlink_to(tmp_path / "uninstalled" / "python3.12")
    (venv / "pyvenv.cfg").write_text("home = /usr/bin\n")

    heal_venv(venv)

    assert not venv.exists()


def test_a_leftover_dir_with_no_interpreter_is_removed(tmp_path: Path) -> None:
    """The runner's shape: uv refuses a dir with neither pyvenv.cfg nor bin/python."""
    venv = tmp_path / ".venv-voice-agent"
    (venv / "lib").mkdir(parents=True)

    heal_venv(venv)

    assert not venv.exists()


def test_a_venv_missing_pyvenv_cfg_is_removed(tmp_path: Path) -> None:
    """It passes uv sync --check and the -x probe while every import fails; uv sync keeps it."""
    venv = tmp_path / ".venv"
    healthy_venv(venv)
    (venv / "pyvenv.cfg").unlink()

    heal_venv(venv)

    assert not venv.exists()


def test_a_venv_with_a_runnable_interpreter_and_config_is_kept(tmp_path: Path) -> None:
    venv = tmp_path / ".venv"
    healthy_venv(venv)

    heal_venv(venv)

    assert (venv / "bin" / "python").exists()
    assert (venv / "pyvenv.cfg").exists()


def test_an_absent_venv_is_left_for_uv_to_create(tmp_path: Path) -> None:
    heal_venv(tmp_path / ".venv")

    assert not (tmp_path / ".venv").exists()


def test_an_unknown_subcommand_prints_the_whole_usage_block() -> None:
    proc = subprocess.run(
        ["python3", str(RUNNER), "no-such-subcommand"],
        env={"PATH": os.environ["PATH"]},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 2
    for subcommand in ("select", "watchdog", "parallel", "with-slots", "health"):
        assert subcommand in proc.stderr, f"usage does not reach '{subcommand}'"


def test_run_job_refuses_to_post_without_this_jobs_check_run_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("GITHUB_REPOSITORY", "HEAD_SHA", "GITHUB_RUN_ID"):
        monkeypatch.setenv(name, "x")
    monkeypatch.delenv("NO_POST", raising=False)
    monkeypatch.setenv("JOB_CHECK_RUN_ID", "")

    with pytest.raises(runner_mod.Die, match="JOB_CHECK_RUN_ID"):
        runner_mod._post_target()
