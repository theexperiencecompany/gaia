"""Every released image is stamped with the commit under release, not whatever HEAD is when it builds.

build.yml releases the apps group, then the bots group, in one checkout. nx release
commits "chore(release): publish" locally after the first, so a build that reads
git rev-parse HEAD in the second is stamped with a commit that exists nowhere else:
the bots logged that as their commit on every deploy that also released the API.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
BUILD_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "build.yml"
RELEASED = "0123456789abcdef0123456789abcdef01234567"
GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
}


def _docker_builds() -> dict[str, str]:
    """Return each released project's docker:build command, by project name."""
    builds = {}
    for path in sorted(REPO_ROOT.glob("apps/**/project.json")):
        if "node_modules" in path.parts:
            continue
        project = json.loads(path.read_text())
        if any(tag.startswith("release:") for tag in project.get("tags", [])):
            builds[project["name"]] = project["targets"]["docker:build"]["options"]["command"]
    return builds


DOCKER_BUILDS = _docker_builds()


def _git(checkout: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=checkout,
        env={"PATH": os.environ["PATH"]} | GIT_ENV,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    """Return a checkout whose HEAD is a commit made after the one under release, as nx release leaves it."""
    repo = tmp_path / "checkout"
    repo.mkdir()
    _git(repo, "init", "--quiet")
    _git(repo, "commit", "--quiet", "--allow-empty", "--message", "chore(release): publish")
    return repo


def _stamped(command: str, checkout: Path, tmp_path: Path, env: dict[str, str]) -> str:
    """Run a docker:build command against a docker that records its arguments; return the commit build arg."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    recorded = tmp_path / "docker-args"
    stub = bin_dir / "docker"
    stub.write_text(f'#!/usr/bin/env bash\nprintf "%s\\n" "$@" > "{recorded}"\n')
    stub.chmod(0o755)
    subprocess.run(
        ["bash", "-c", command],
        cwd=checkout,
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}"} | GIT_ENV | env,
        capture_output=True,
        text=True,
        check=True,
    )
    [stamped] = [
        arg.removeprefix("GIT_COMMIT_SHA=")
        for arg in recorded.read_text().splitlines()
        if arg.startswith("GIT_COMMIT_SHA=")
    ]
    return stamped


def test_every_release_group_project_is_covered() -> None:
    assert {"api", "voice-agent", "bot-discord", "bot-telegram"} <= set(DOCKER_BUILDS)


@pytest.mark.parametrize("project", sorted(DOCKER_BUILDS))
def test_a_release_build_is_stamped_with_the_commit_under_release_after_head_moved(
    project: str, checkout: Path, tmp_path: Path
) -> None:
    stamped = _stamped(DOCKER_BUILDS[project], checkout, tmp_path, {"GIT_COMMIT_SHA": RELEASED})

    assert stamped == RELEASED != _git(checkout, "rev-parse", "HEAD")


@pytest.mark.parametrize("project", sorted(DOCKER_BUILDS))
def test_a_local_build_is_stamped_with_head(project: str, checkout: Path, tmp_path: Path) -> None:
    assert _stamped(DOCKER_BUILDS[project], checkout, tmp_path, {}) == _git(
        checkout, "rev-parse", "HEAD"
    )


def test_every_nx_release_step_names_the_commit_under_release() -> None:
    steps = yaml.safe_load(BUILD_WORKFLOW.read_text())["jobs"]["docker-release"]["steps"]
    releases = [step for step in steps if "nx release" in step.get("run", "")]

    assert [step["id"] for step in releases] == ["release-apps", "release-bots"]
    assert [step.get("env", {}).get("GIT_COMMIT_SHA") for step in releases] == [
        "${{ github.sha }}"
    ] * 2
