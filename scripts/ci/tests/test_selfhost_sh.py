"""`selfhost.sh` boots the checkout under test and freezes exactly the stack's MongoDB.

`gaia up` boots the CLI's recorded install, so `prepare` must record THIS
checkout or the lane would clone master and test that instead. `mongo` must
target the self-host project's mongo container, never another project's.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "ci" / "selfhost.sh"

# `docker ps -aq --filter ...` answers the mongo container id only for the
# gaia-selfhost project's mongo service; every call is recorded in $DOCKER_CALLS.
DOCKER_STUB = """#!/usr/bin/env bash
set -euo pipefail
echo "$*" >> "$DOCKER_CALLS"
if [[ "$1" == "ps" ]]; then
  [[ "$*" == *"com.docker.compose.project=gaia-selfhost"* \\
    && "$*" == *"com.docker.compose.service=mongo"* ]] && echo "mongo-cid"
  exit 0
fi
"""


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "docker"
    stub.write_text(DOCKER_STUB)
    stub.chmod(0o755)
    home = tmp_path / "home"
    home.mkdir()
    result = dict(os.environ)
    result.update(
        PATH=f"{bin_dir}{os.pathsep}{result['PATH']}",
        HOME=str(home),
        DOCKER_CALLS=str(tmp_path / "docker-calls.txt"),
    )
    result.pop("GITHUB_ACTIONS", None)
    return result


def _run(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), *args], env=env, capture_output=True, text=True, check=False
    )


def test_prepare_records_this_checkout_as_the_install(env: dict[str, str]) -> None:
    result = _run(env, "prepare")

    assert result.returncode == 0, result.stderr
    config = json.loads((Path(env["HOME"]) / ".gaia" / "config.json").read_text())
    assert config == {"repoPath": str(REPO_ROOT)}


def test_mongo_pause_freezes_the_selfhost_mongo_container(env: dict[str, str]) -> None:
    result = _run(env, "mongo", "pause")

    assert result.returncode == 0, result.stderr
    assert Path(env["DOCKER_CALLS"]).read_text().splitlines()[-1] == "pause mongo-cid"


def test_mongo_refuses_an_unknown_action(env: dict[str, str]) -> None:
    result = _run(env, "mongo", "stop")

    assert result.returncode != 0
    assert not Path(env["DOCKER_CALLS"]).exists()
