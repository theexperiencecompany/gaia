"""runner.py select: trust gates and per-class routing, against a local fake GitHub.

The home box runs only code from organisation members, and every trust gate is
decided before any API call, so a gate that leaks shows up as a request to the
fake server. Routing is GitHub-hosted first for every class, the box only once
GitHub's queue is saturated, and Blacksmith only when the box has no idle listener.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess

from github_fake import REPO, RUNNER, FakeGitHub, Reply, run_runner, runner
import pytest

HOME = '["self-hosted","gaia-home"]'
HOSTED = '["ubuntu-latest"]'
BLACKSMITH = "blacksmith-4vcpu-ubuntu-2404"
RUNNERS = r"/actions/runners$"
RUNS = r"/actions/runs$"


def select(github: FakeGitHub, **env: str) -> dict[str, str]:
    proc = run_runner("select", env=github.env(**{"PR_HEAD_REPO": REPO, **env}))
    assert proc.returncode == 0, proc.stderr
    return dict(line.split("=", 1) for line in proc.stdout.splitlines() if "=" in line)


def pool(github: FakeGitHub, *runners: dict[str, object]) -> None:
    github.on("GET", RUNNERS, Reply(200, {"runners": list(runners)}))


def queued_jobs(github: FakeGitHub, status: str, labels: list[str], count: int) -> None:
    """Serve one sampled run of the given status holding count jobs queued on labels."""
    run_id = 500 if status == "queued" else 600
    github.on(
        "GET", RUNS, Reply(200, {"workflow_runs": [{"id": run_id}]}), query={"status": status}
    )
    jobs = [{"name": f"j{i}", "status": "queued", "labels": labels} for i in range(count)]
    github.on("GET", rf"/actions/runs/{run_id}/jobs$", Reply(200, {"jobs": jobs}))


def no_runs(github: FakeGitHub) -> None:
    github.on("GET", RUNS, Reply(200, {"workflow_runs": []}))


def saturate(github: FakeGitHub, depth: int = 5) -> None:
    """Serve a GitHub-hosted backlog of depth queued jobs."""
    queued_jobs(github, "queued", ["ubuntu-latest"], depth)
    queued_jobs(github, "in_progress", ["ubuntu-latest"], 0)


# ── trust gates: decided before any probe ───────────────────────────────────


@pytest.mark.parametrize(
    "association", ["COLLABORATOR", "CONTRIBUTOR", "FIRST_TIME_CONTRIBUTOR", "FIRST_TIMER", "NONE"]
)
def test_non_member_pr_never_reaches_the_box(github: FakeGitHub, association: str) -> None:
    out = select(github, PR_AUTHOR_ASSOCIATION=association)
    assert out["is_self_hosted"] == "false"
    assert out["reason"] == "untrusted-author"
    assert out["light"] == out["heavy"] == out["services"] == HOSTED
    assert github.requests == []


def test_fork_pr_is_rejected_before_the_author_check(github: FakeGitHub) -> None:
    out = select(github, PR_HEAD_REPO="outsider/gaia", PR_AUTHOR_ASSOCIATION="MEMBER")
    assert out["light"] == out["heavy"] == out["services"] == HOSTED
    assert out["reason"] == "fork"
    assert github.requests == []


@pytest.mark.parametrize("actor", ["dependabot[bot]", "github-actions[bot]", "renovate[bot]"])
def test_bot_actor_never_reaches_the_box(github: FakeGitHub, actor: str) -> None:
    out = select(github, PR_AUTHOR_ASSOCIATION="MEMBER", GITHUB_ACTOR=actor)
    assert out["light"] == out["heavy"] == out["services"] == HOSTED
    assert out["reason"] == "bot-actor"
    assert github.requests == []


def test_forced_github_skips_the_probe(github: FakeGitHub) -> None:
    out = select(github, PR_AUTHOR_ASSOCIATION="OWNER", FORCE_GITHUB="true")
    assert out["light"] == out["heavy"] == out["services"] == HOSTED
    assert out["reason"] == "forced-github"
    assert github.requests == []


@pytest.mark.parametrize("association", ["OWNER", "MEMBER", ""])
def test_member_pr_and_push_reach_the_probe(github: FakeGitHub, association: str) -> None:
    no_runs(github)
    out = select(github, PR_AUTHOR_ASSOCIATION=association)
    assert out["reason"] == "github-hosted"
    assert any(re.search(RUNS, r.path) for r in github.requests)


# ── routing: GitHub-hosted first, the box as overflow, Blacksmith last ──────


def test_a_free_github_queue_keeps_every_class_off_an_idle_box(github: FakeGitHub) -> None:
    pool(github, runner("home-1", "online", "gaia-home"))
    no_runs(github)
    out = select(github, BLACKSMITH_LABEL=BLACKSMITH)
    assert out["light"] == out["heavy"] == out["services"] == HOSTED
    assert out["reason"] == "github-hosted"
    assert out["is_self_hosted"] == "false"
    assert not any(re.search(RUNNERS, r.path) for r in github.requests)


@pytest.mark.parametrize(("depth", "expected"), [(4, HOSTED), (5, HOME)])
def test_the_default_saturation_threshold_is_five_queued_jobs(
    github: FakeGitHub, depth: int, expected: str
) -> None:
    pool(github, *idle_home(18))
    saturate(github, depth)
    out = select(github)
    assert out["heavy"] == expected


def idle_home(count: int, busy: int = 0) -> list[dict[str, object]]:
    return [runner(f"home-{i}", "online", "gaia-home", busy=i < busy) for i in range(busy + count)]


def test_a_saturated_github_queue_overflows_every_class_to_a_box_that_fits_them(
    github: FakeGitHub,
) -> None:
    pool(github, *idle_home(sum(ci_class_demand().values()), busy=2))
    saturate(github)
    out = select(github, BLACKSMITH_LABEL=BLACKSMITH)
    assert out["light"] == out["heavy"] == out["services"] == HOME
    assert out["reason"] == "home-overflow"
    assert out["is_self_hosted"] == "true"


def test_one_idle_listener_takes_no_class_it_cannot_fit(github: FakeGitHub) -> None:
    """Every job of a class goes to one label, so a class needing 5 listeners would queue behind 1."""
    pool(github, *idle_home(1, busy=9))
    saturate(github)
    out = select(github, BLACKSMITH_LABEL=BLACKSMITH)
    assert out["light"] == out["heavy"] == out["services"] == f'["{BLACKSMITH}"]'


@pytest.mark.parametrize(
    ("idle", "on_box"),
    [(5, {"heavy"}), (9, {"services"}), (14, {"services", "heavy"}), (19, {"services", "heavy"})],
)
def test_idle_listeners_are_shared_out_class_by_class(
    github: FakeGitHub, idle: int, on_box: set[str]
) -> None:
    pool(github, *idle_home(idle))
    saturate(github)
    out = select(github, BLACKSMITH_LABEL=BLACKSMITH)
    assert {cls for cls in ("light", "heavy", "services") if out[cls] == HOME} == on_box


def ci_class_demand() -> dict[str, int]:
    """Count the jobs ci.yml routes to each class; a matrix counts at its concurrent width."""
    repo = RUNNER.parent.parent.parent
    workflow = (repo / ".github/workflows/ci.yml").read_text()
    routed: dict[str, list[str]] = {"light": [], "heavy": [], "services": []}
    job = ""
    for line in workflow.splitlines():
        if match := re.match(r"^  ([a-z][a-z0-9_-]*):$", line):
            job = match.group(1)
        elif "runs-on:" in line and job != "test-python":
            if match := re.search(r"select-runner\.outputs\.(light|heavy|services)\)", line):
                routed[match.group(1)].append(job)
    assert routed["services"] == ["test-python-engines", "test-mutation"]
    split = "[matrix.slice].services == 'true' && fromJSON(needs.select-runner.outputs.services)"
    assert split in workflow, "test-python no longer picks its pool per slice"
    slices = json.loads((repo / "scripts/ci/lib/test-slices.json").read_text())["slices"]
    services = sum(1 for s in slices if s["services"] == "true")
    wave = re.search(r"max-parallel: (\d+)", workflow[workflow.index("\n  test-mutation:") :])
    assert wave is not None
    return {
        "light": len(routed["light"]),
        "heavy": len(routed["heavy"]) + len(slices) - services,
        "services": services + int(wave.group(1)),
    }


@pytest.mark.parametrize("short", [0, 1])
def test_the_box_takes_every_class_only_with_a_listener_per_ci_job(
    github: FakeGitHub, short: int
) -> None:
    """A lane added to a class must raise that class's demand, or its jobs queue on the box."""
    pool(github, *idle_home(sum(ci_class_demand().values()) - short))
    saturate(github)
    out = select(github, BLACKSMITH_LABEL=BLACKSMITH)
    every = out["light"] == out["heavy"] == out["services"] == HOME
    assert every is (short == 0)


@pytest.mark.parametrize(
    "listeners",
    [
        idle_home(0, busy=10),
        [runner("home-1", "offline", "gaia-home")],
        [runner("lint-1", "online", "gaia-home-lint")],
    ],
    ids=["busy", "offline", "not-registered"],
)
def test_a_saturated_github_and_a_box_with_no_idle_listener_go_to_blacksmith(
    github: FakeGitHub, listeners: list[dict[str, object]]
) -> None:
    pool(github, *listeners)
    saturate(github)
    out = select(github, BLACKSMITH_LABEL=BLACKSMITH)
    assert out["light"] == out["heavy"] == out["services"] == f'["{BLACKSMITH}"]'
    assert out["reason"] == "blacksmith-overflow"
    assert out["is_self_hosted"] == "false"


def test_without_blacksmith_a_saturated_everything_queues_on_github(github: FakeGitHub) -> None:
    pool(github, runner("home-1", "online", "gaia-home", busy=True))
    saturate(github)
    out = select(github)
    assert out["light"] == out["heavy"] == out["services"] == HOSTED
    assert out["reason"] == "github-queued"


def test_an_unreadable_runners_list_is_loud_and_skips_the_box(github: FakeGitHub) -> None:
    github.on("GET", RUNNERS, Reply(401, {"message": "Bad credentials"}))
    saturate(github)
    proc = run_runner("select", env=github.env(PR_HEAD_REPO=REPO, BLACKSMITH_LABEL=BLACKSMITH))
    assert proc.returncode == 0, proc.stderr
    assert "::warning::runners API unavailable" in proc.stderr
    assert f'heavy=["{BLACKSMITH}"]' in proc.stdout


def test_a_custom_threshold_overrides_the_default(github: FakeGitHub) -> None:
    pool(github, runner("home-1", "online", "gaia-home"))
    saturate(github, 8)
    out = select(github, HOSTED_QUEUE_THRESHOLD="9")
    assert out["heavy"] == HOSTED


@pytest.mark.parametrize("busy", [False, True])
def test_force_home_takes_an_online_box_over_a_free_github(github: FakeGitHub, busy: bool) -> None:
    pool(github, runner("home-1", "online", "gaia-home", busy=busy))
    no_runs(github)
    out = select(github, FORCE_HOME="true")
    assert out["light"] == out["heavy"] == out["services"] == HOME
    assert out["reason"] == "forced-home"


def test_force_home_dies_rather_than_fall_back(github: FakeGitHub) -> None:
    pool(github, runner("home-1", "offline", "gaia-home"))
    no_runs(github)
    proc = run_runner("select", env=github.env(FORCE_HOME="true"))
    assert proc.returncode == 1
    assert "::error::" in proc.stderr
    assert "heavy=" not in proc.stdout


def test_services_probe_their_own_label(github: FakeGitHub) -> None:
    """A dispatch may point heavy at a trial pool; services must stay on the pool with services."""
    trial = [runner(f"trial-{i}", "online", "gaia-trial") for i in range(9)]
    pool(github, *trial, runner("home-1", "offline", "gaia-home"))
    saturate(github)
    out = select(github, RUNNER_LABEL="gaia-trial")
    assert out["heavy"] == '["self-hosted","gaia-trial"]'
    assert out["services"] == HOSTED


def test_jobs_queued_for_the_home_box_are_not_github_saturation(github: FakeGitHub) -> None:
    """The in-progress half once counted home-label jobs too, reading the box's queue as GitHub's."""
    pool(github, runner("home-1", "online", "gaia-home"))
    no_runs(github)
    queued_jobs(github, "in_progress", ["self-hosted", "gaia-home"], 30)
    out = select(github, BLACKSMITH_LABEL=BLACKSMITH)
    assert out["heavy"] == HOSTED
    assert out["reason"] == "github-hosted"


def test_an_unreadable_hosted_queue_is_not_an_empty_one(github: FakeGitHub) -> None:
    """A 200 whose body has no workflow_runs is a failed probe, not a queue of zero."""
    pool(github, runner("home-1", "online", "gaia-home"))
    github.on("GET", RUNS, Reply(200, {"message": "Server Error"}))
    proc = run_runner("select", env=github.env(PR_HEAD_REPO=REPO, BLACKSMITH_LABEL=BLACKSMITH))
    assert proc.returncode == 0, proc.stderr
    assert "::warning::hosted queue probe failed" in proc.stderr
    assert "heavy=" + HOSTED in proc.stdout
    assert "reason=hosted-queue-unknown" in proc.stdout


def test_a_runners_listing_spanning_pages_is_read_whole(github: FakeGitHub) -> None:
    """The box has more listeners than one page holds; the home pool may be on page two."""
    page_two = f"{github.url}/repos/theexperiencecompany/gaia/actions/runners?page=2"
    lint = runner("lint-1", "online", "gaia-home-lint")
    github.on("GET", RUNNERS, Reply(200, {"runners": [lint]}, link=f'<{page_two}>; rel="next"'))
    github.on("GET", RUNNERS, Reply(200, {"runners": idle_home(18)}), query={"page": "2"})
    saturate(github)
    out = select(github)
    assert out["heavy"] == HOME
    assert out["reason"] == "home-overflow"


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
    for output in ("light", "heavy", "services"):
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
