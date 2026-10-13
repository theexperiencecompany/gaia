"""`release.sh resolve-image-tags` names the image tags this run pushed, for every scheme.

A branch dispatch (develop scheme) must resolve its develop-<sha> tag too: the
multi-arch API manifest job runs only when apps_tag is non-empty, and a
self-host end-to-end run pins GAIA_VERSION to the commit it builds.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
RELEASE_SH = REPO_ROOT / "scripts" / "ci" / "release.sh"

# Answers `docker image ls --format '{{.Tag}}' <repo>` from $LOCAL_TAGS (one
# tag per line, any repo) and treats every pushed ref as present in GHCR.
DOCKER_STUB = """#!/usr/bin/env bash
set -euo pipefail
case "$1 $2" in
  "image ls") cat "$LOCAL_TAGS" ;;
  "manifest inspect") exit 0 ;;
  *) echo "docker stub: unexpected $*" >&2; exit 1 ;;
esac
"""


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "docker"
    stub.write_text(DOCKER_STUB)
    stub.chmod(0o755)
    return tmp_path


def _resolve(workspace: Path, *, scheme: str, local_tags: list[str]) -> dict[str, str]:
    (workspace / "tags.txt").write_text("\n".join(local_tags) + "\n")
    output = workspace / "github-output.txt"
    output.write_text("")
    env = dict(os.environ)
    env.update(
        PATH=f"{workspace / 'bin'}{os.pathsep}{env['PATH']}",
        LOCAL_TAGS=str(workspace / "tags.txt"),
        GITHUB_OUTPUT=str(output),
        VERSION_SCHEME=scheme,
        APPS_RELEASE_OUTCOME="success",
        BOTS_RELEASE_OUTCOME="skipped",
    )
    env.pop("GITHUB_STEP_SUMMARY", None)
    subprocess.run(
        ["bash", str(RELEASE_SH), "resolve-image-tags"],
        cwd=workspace,
        check=True,
        env=env,
        capture_output=True,
        text=True,
    )
    return dict(line.split("=", 1) for line in output.read_text().splitlines())


def test_a_master_run_resolves_its_production_tag(workspace: Path) -> None:
    outputs = _resolve(workspace, scheme="production", local_tags=["latest", "2610.13.716f03d"])

    assert outputs["apps_tag"] == "2610.13.716f03d"


def test_a_branch_run_resolves_its_develop_tag(workspace: Path) -> None:
    outputs = _resolve(workspace, scheme="develop", local_tags=["latest", "develop-716f03d"])

    assert outputs["apps_tag"] == "develop-716f03d"


def test_a_group_not_released_this_run_resolves_empty(workspace: Path) -> None:
    outputs = _resolve(workspace, scheme="develop", local_tags=["develop-716f03d"])

    assert outputs["bots_tag"] == ""
