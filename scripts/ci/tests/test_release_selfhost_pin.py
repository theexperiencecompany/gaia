"""A CLI release pins the gaia, gaia-web and self-host bot images built from its own release commit.

`gaia update` pins GAIA_VERSION=v<CLI version>; tagging that from :latest pinned
whatever master last deployed, not the code the CLI was released with. The pin
now waits for build.yml's per-commit :<sha> pair and fails loud when it never
appears, and build.yml must publish that pair for every CLI release commit.
The :<sha> images exist before ci.yml's quality gate has judged that commit,
so the pin also waits for the gate to pass on it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import subprocess

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
RELEASE_SH = REPO_ROOT / "scripts" / "ci" / "release.sh"
NAMESPACE = "ghcr.io/theexperiencecompany"
RELEASE_REPOS = ("gaia", "gaia-web", "gaia-bot-telegram", "gaia-bot-discord", "gaia-bot-slack")

# `imagetools inspect <ref>` succeeds when <ref> is in $PRESENT, or when it is
# listed in $LATE as "<ref> <n>" and has been inspected more than n times.
# `imagetools create -t <dst> <src>...` records "<dst> <src>..." in $CREATED.
DOCKER_STUB = """#!/usr/bin/env bash
set -euo pipefail
[[ "$1 $2" == "buildx imagetools" ]] || { echo "docker stub: unexpected $*" >&2; exit 1; }
case "$3" in
  inspect)
    ref="$4"
    grep -qxF "$ref" "$PRESENT" && exit 0
    late=$(awk -v r="$ref" '$1 == r {print $2}' "$LATE")
    [[ -n "$late" ]] || exit 1
    echo "$ref" >> "$INSPECTED"
    seen=$(grep -cxF "$ref" "$INSPECTED")
    (( seen > late )) && exit 0
    exit 1
    ;;
  create) echo "${*:5}" >> "$CREATED" ;;
  *) echo "docker stub: unexpected $*" >&2; exit 1 ;;
esac
"""


# `gh api <path> --jq <expr>` answers from the JSON fixture for <path>, filtered
# by the real jq, so the script's jq expressions are exercised too.
GH_STUB = """#!/usr/bin/env bash
set -euo pipefail
[[ "$1" == "api" && "$3" == "--jq" ]] || { echo "gh stub: unexpected $*" >&2; exit 1; }
echo "$2" >> "$GH_CALLS"
case "$2" in
  */actions/workflows/ci.yml/runs\\?*) file="$GH_FIXTURES/runs-${2##*event=}.json" ;;
  */actions/runs/*/jobs*) id="${2#*/actions/runs/}"; file="$GH_FIXTURES/jobs-${id%%/*}.json" ;;
  *) echo "gh stub: unexpected path $2" >&2; exit 1 ;;
esac
jq -r "$4" "$file"
"""

JobState = tuple[str, str | None]
GATE_PASSED: dict[str, JobState] = {"quality-gate": ("completed", "success")}


MainRuns = dict[int, dict[str, JobState]]


@dataclass(frozen=True)
class GitHubState:
    """What the stubbed registry and Actions API report: images, late images, gate runs."""

    present: list[str] = field(default_factory=list)
    late: dict[str, int] = field(default_factory=dict)
    main_runs: MainRuns = field(default_factory=lambda: {1: GATE_PASSED})
    pr_runs: MainRuns = field(default_factory=dict)


def _write_main_runs(workspace: Path, runs_by_event: dict[str, MainRuns]) -> None:
    fixtures = workspace / "gh"
    for event, runs in runs_by_event.items():
        (fixtures / f"runs-{event}.json").write_text(
            json.dumps({"workflow_runs": [{"id": run_id} for run_id in runs]})
        )
    for run_id, jobs in (item for runs in runs_by_event.values() for item in runs.items()):
        (fixtures / f"jobs-{run_id}.json").write_text(
            json.dumps(
                {
                    "jobs": [
                        {"name": name, "status": status, "conclusion": conclusion}
                        for name, (status, conclusion) in jobs.items()
                    ]
                }
            )
        )


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "docker"
    stub.write_text(DOCKER_STUB)
    stub.chmod(0o755)
    gh_stub = bin_dir / "gh"
    gh_stub.write_text(GH_STUB)
    gh_stub.chmod(0o755)
    (tmp_path / "gh").mkdir()
    (tmp_path / "gh-calls.txt").write_text("")
    for name in ("present.txt", "late.txt", "inspected.txt", "created.txt"):
        (tmp_path / name).write_text("")
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "ci@example.com")
    _git(repo, "config", "user.name", "ci")
    (repo / "packages" / "cli").mkdir(parents=True)
    (repo / "packages" / "cli" / "package.json").write_text(
        '{\n  "name": "@heygaia/cli",\n  "version": "0.6.0"\n}\n'
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "initial")
    return tmp_path


def _head(workspace: Path) -> str:
    return _git(workspace / "repo", "rev-parse", "HEAD")


def _run(
    workspace: Path,
    subcommand: str,
    *,
    github: GitHubState | None = None,
    env_extra: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    state = github or GitHubState()
    _write_main_runs(workspace, {"push": state.main_runs, "pull_request": state.pr_runs})
    (workspace / "present.txt").write_text("".join(f"{r}\n" for r in state.present))
    (workspace / "late.txt").write_text("".join(f"{r} {n}\n" for r, n in state.late.items()))
    env = dict(os.environ)
    env.update(
        PATH=f"{workspace / 'bin'}{os.pathsep}{env['PATH']}",
        PRESENT=str(workspace / "present.txt"),
        LATE=str(workspace / "late.txt"),
        INSPECTED=str(workspace / "inspected.txt"),
        CREATED=str(workspace / "created.txt"),
        GH_FIXTURES=str(workspace / "gh"),
        GH_CALLS=str(workspace / "gh-calls.txt"),
        GITHUB_REPOSITORY="theexperiencecompany/gaia",
        PIN_POLL_SECONDS="0",
        GITHUB_OUTPUT=str(workspace / "github-output.txt"),
    )
    env.pop("GITHUB_STEP_SUMMARY", None)
    env.update(env_extra or {})
    return subprocess.run(
        ["bash", str(RELEASE_SH), subcommand],
        cwd=workspace / "repo",
        check=False,
        env=env,
        capture_output=True,
        text=True,
    )


def _pin(
    workspace: Path,
    github: GitHubState,
    *,
    version: str = "0.6.0",
    env_extra: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = {"VERSION": version, "SHA": _head(workspace), **(env_extra or {})}
    return _run(workspace, "pin-selfhost-release", github=github, env_extra=env)


def _created(workspace: Path) -> list[str]:
    return (workspace / "created.txt").read_text().splitlines()


def _release_images(sha: str, *, without: str = "") -> list[str]:
    return [f"{NAMESPACE}/{repo}:{sha}" for repo in RELEASE_REPOS if repo != without]


def test_the_release_pins_the_images_of_its_own_commit(workspace: Path) -> None:
    sha = _head(workspace)
    result = _pin(workspace, GitHubState(present=_release_images(sha)))

    assert result.returncode == 0, result.stderr
    assert _created(workspace) == [
        f"{NAMESPACE}/{repo}:v0.6.0 {NAMESPACE}/{repo}:{sha}" for repo in RELEASE_REPOS
    ]


def test_the_pin_waits_for_a_build_still_in_flight(workspace: Path) -> None:
    sha = _head(workspace)
    result = _pin(
        workspace,
        GitHubState(
            present=_release_images(sha, without="gaia-web"),
            late={f"{NAMESPACE}/gaia-web:{sha}": 2},
        ),
    )

    assert result.returncode == 0, result.stderr
    assert f"{NAMESPACE}/gaia-web:v0.6.0 {NAMESPACE}/gaia-web:{sha}" in _created(workspace)


def test_a_missing_image_times_out_loud_and_tags_nothing(workspace: Path) -> None:
    sha = _head(workspace)
    result = _pin(
        workspace,
        GitHubState(present=[f"{NAMESPACE}/gaia:{sha}"]),
        env_extra={"PIN_WAIT_SECONDS": "0"},
    )

    assert result.returncode != 0
    assert f"gaia-web:{sha}" in result.stderr
    assert _created(workspace) == []


def test_a_release_without_its_bot_images_times_out_loud_and_tags_nothing(
    workspace: Path,
) -> None:
    sha = _head(workspace)
    result = _pin(
        workspace,
        GitHubState(present=_release_images(sha, without="gaia-bot-slack")),
        env_extra={"PIN_WAIT_SECONDS": "0"},
    )

    assert result.returncode != 0
    assert f"gaia-bot-slack:{sha}" in result.stderr
    assert _created(workspace) == []


def test_an_existing_release_tag_is_never_moved(workspace: Path) -> None:
    sha = _head(workspace)
    result = _pin(
        workspace, GitHubState(present=[f"{NAMESPACE}/gaia:v0.6.0", *_release_images(sha)])
    )

    assert result.returncode == 0, result.stderr
    assert _created(workspace) == [
        f"{NAMESPACE}/{repo}:v0.6.0 {NAMESPACE}/{repo}:{sha}" for repo in RELEASE_REPOS[1:]
    ]


def test_a_sha_other_than_the_checked_out_release_is_refused(workspace: Path) -> None:
    other = "0" * 40
    result = _pin(
        workspace,
        GitHubState(present=[f"{NAMESPACE}/gaia:{other}", f"{NAMESPACE}/gaia-web:{other}"]),
        env_extra={"SHA": other},
    )

    assert result.returncode != 0
    assert _created(workspace) == []


def test_the_pin_asks_for_the_quality_gate_of_the_release_commit(workspace: Path) -> None:
    sha = _head(workspace)
    result = _pin(workspace, GitHubState(present=_release_images(sha)))

    assert result.returncode == 0, result.stderr
    calls = (workspace / "gh-calls.txt").read_text()
    assert f"repos/theexperiencecompany/gaia/actions/workflows/ci.yml/runs?head_sha={sha}" in calls


def test_a_failed_quality_gate_refuses_the_release_and_tags_nothing(workspace: Path) -> None:
    sha = _head(workspace)
    result = _pin(
        workspace,
        GitHubState(
            present=_release_images(sha), main_runs={7: {"quality-gate": ("completed", "failure")}}
        ),
    )

    assert result.returncode != 0
    assert "quality gate" in result.stderr
    assert _created(workspace) == []


def test_a_gate_that_never_finishes_times_out_loud_and_tags_nothing(workspace: Path) -> None:
    sha = _head(workspace)
    result = _pin(
        workspace,
        GitHubState(
            present=_release_images(sha), main_runs={7: {"quality-gate": ("in_progress", None)}}
        ),
        env_extra={"PIN_WAIT_SECONDS": "0"},
    )

    assert result.returncode != 0
    assert "quality gate" in result.stderr
    assert _created(workspace) == []


def test_a_commit_main_yml_never_ran_on_is_not_released(workspace: Path) -> None:
    sha = _head(workspace)
    result = _pin(
        workspace,
        GitHubState(present=_release_images(sha), main_runs={}),
        env_extra={"PIN_WAIT_SECONDS": "0"},
    )

    assert result.returncode != 0
    assert _created(workspace) == []


def test_a_passed_gate_releases_even_when_a_non_gating_job_failed(workspace: Path) -> None:
    sha = _head(workspace)
    result = _pin(
        workspace,
        GitHubState(
            present=_release_images(sha),
            main_runs={
                7: {
                    "changelog-sync": ("completed", "failure"),
                    "quality-gate": ("completed", "success"),
                }
            },
        ),
    )

    assert result.returncode == 0, result.stderr
    assert len(_created(workspace)) == len(RELEASE_REPOS)


def test_a_beta_cut_from_a_pr_head_is_judged_by_that_prs_gate(workspace: Path) -> None:
    sha = _head(workspace)
    result = _pin(
        workspace,
        GitHubState(present=_release_images(sha), main_runs={}, pr_runs={8: GATE_PASSED}),
        version="0.7.0-beta.1",
        env_extra={"PIN_WAIT_SECONDS": "0"},
    )

    assert result.returncode == 0, result.stderr
    assert _created(workspace) == [
        f"{NAMESPACE}/{repo}:v0.7.0-beta.1 {NAMESPACE}/{repo}:{sha}" for repo in RELEASE_REPOS
    ]
    assert f"head_sha={sha}&event=pull_request" in (workspace / "gh-calls.txt").read_text()


def test_a_beta_whose_pr_gate_failed_is_refused_and_tags_nothing(workspace: Path) -> None:
    result = _pin(
        workspace,
        GitHubState(
            present=_release_images(_head(workspace)),
            main_runs={},
            pr_runs={8: {"quality-gate": ("completed", "failure")}},
        ),
        version="0.7.0-beta.1",
        env_extra={"PIN_WAIT_SECONDS": "0"},
    )

    assert result.returncode != 0
    assert "quality gate failed" in result.stderr
    assert _created(workspace) == []


def test_a_beta_whose_pr_gate_is_still_running_times_out_and_tags_nothing(
    workspace: Path,
) -> None:
    result = _pin(
        workspace,
        GitHubState(
            present=_release_images(_head(workspace)),
            main_runs={},
            pr_runs={8: {"quality-gate": ("in_progress", None)}},
        ),
        version="0.7.0-beta.1",
        env_extra={"PIN_WAIT_SECONDS": "0"},
    )

    assert result.returncode != 0
    assert _created(workspace) == []


def test_a_stable_release_never_accepts_a_pr_gate(workspace: Path) -> None:
    sha = _head(workspace)
    result = _pin(
        workspace,
        GitHubState(present=_release_images(sha), main_runs={}, pr_runs={8: GATE_PASSED}),
        env_extra={"PIN_WAIT_SECONDS": "0"},
    )

    assert result.returncode != 0
    assert _created(workspace) == []
    assert "event=pull_request" not in (workspace / "gh-calls.txt").read_text()


def test_an_unreadable_actions_api_fails_the_pin_loud(workspace: Path) -> None:
    sha = _head(workspace)
    result = _pin(
        workspace,
        GitHubState(present=_release_images(sha)),
        env_extra={"GH_FIXTURES": str(workspace / "absent"), "PIN_WAIT_SECONDS": "0"},
    )

    assert result.returncode != 0
    assert "could not read ci.yml's runs" in result.stderr
    assert _created(workspace) == []


def _commit(workspace: Path, path: str, body: str) -> None:
    repo = workspace / "repo"
    (repo / path).parent.mkdir(parents=True, exist_ok=True)
    (repo / path).write_text(body)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "change")


def _cli_release_images(workspace: Path) -> str:
    result = _run(workspace, "cli-release-images")
    assert result.returncode == 0, result.stderr
    return (workspace / "github-output.txt").read_text().strip()


def test_a_commit_that_bumps_the_cli_version_requires_its_images(
    workspace: Path,
) -> None:
    _commit(
        workspace,
        "packages/cli/package.json",
        '{\n  "name": "@heygaia/cli",\n  "version": "0.7.0"\n}\n',
    )

    assert _cli_release_images(workspace) == "required=true"


def test_a_release_images_dispatch_requires_them_for_any_commit(workspace: Path) -> None:
    result = _run(workspace, "cli-release-images", env_extra={"RELEASE_IMAGES": "true"})

    assert result.returncode == 0, result.stderr
    assert (workspace / "github-output.txt").read_text().strip() == "required=true"


def test_any_other_commit_leaves_the_image_build_to_affected(workspace: Path) -> None:
    _commit(
        workspace,
        "packages/cli/package.json",
        '{\n  "name": "@heygaia/cli",\n  "version": "0.6.0",\n  "private": false\n}\n',
    )

    assert _cli_release_images(workspace) == "required=false"


SELFHOST_BOT_REPOS = RELEASE_REPOS[2:]


def _arm64_digests(*, without: str = "") -> str:
    return " ".join(
        f"{repo}@sha256:{repo[-4:]:0>64}" for repo in SELFHOST_BOT_REPOS if repo != without
    )


def test_each_bot_sha_tag_is_the_release_amd64_image_plus_its_arm64_build(
    workspace: Path,
) -> None:
    sha = _head(workspace)
    result = _run(
        workspace,
        "selfhost-bots-manifest",
        env_extra={
            "BOTS_TAG": "2610.14.abc1234",
            "COMMIT_SHA": sha,
            "ARM64_DIGESTS": _arm64_digests(),
        },
    )

    assert result.returncode == 0, result.stderr
    assert _created(workspace) == [
        f"{NAMESPACE}/{repo}:{sha} {NAMESPACE}/{repo}:2610.14.abc1234 "
        f"{NAMESPACE}/{repo}@sha256:{repo[-4:]:0>64}"
        for repo in SELFHOST_BOT_REPOS
    ]


def test_a_bot_without_an_arm64_build_fails_loud_and_tags_nothing(workspace: Path) -> None:
    result = _run(
        workspace,
        "selfhost-bots-manifest",
        env_extra={
            "BOTS_TAG": "2610.14.abc1234",
            "COMMIT_SHA": _head(workspace),
            "ARM64_DIGESTS": _arm64_digests(without="gaia-bot-discord"),
        },
    )

    assert result.returncode != 0
    assert "gaia-bot-discord" in result.stderr
    assert _created(workspace) == []
