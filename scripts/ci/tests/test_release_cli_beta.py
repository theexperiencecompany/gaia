"""`release.sh cli-beta-release` gives a beta a GitHub Release that is a prerelease, never the latest.

connect.sh and GitHub's "latest release" both skip prereleases, so the flag is
what keeps a beta off every stable install path. gh is a PATH stub whose
`release view` answers from $RELEASE_STATE and which logs every call.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
RELEASE_SH = REPO_ROOT / "scripts" / "ci" / "release.sh"

GH_STUB = """#!/usr/bin/env bash
set -euo pipefail
echo "$*" >> "$GH_CALLS"
if [[ "$1 $2" == "release view" ]]; then
  case "$RELEASE_STATE" in
    absent) exit 1 ;;
    stable) echo false ;;
    prerelease) echo true ;;
  esac
fi
"""


def _run(
    tmp_path: Path, *, tag: str, state: str
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(GH_STUB)
    gh.chmod(0o755)
    calls = tmp_path / "gh-calls.txt"
    calls.write_text("")
    env = dict(os.environ)
    env.update(
        PATH=f"{bin_dir}{os.pathsep}{env['PATH']}",
        GH_CALLS=str(calls),
        GH_TOKEN="t0ken",
        RELEASE_TAG=tag,
        RELEASE_STATE=state,
    )
    result = subprocess.run(
        ["bash", str(RELEASE_SH), "cli-beta-release"],
        check=False,
        env=env,
        capture_output=True,
        text=True,
    )
    return result, calls.read_text().splitlines()


def test_a_new_beta_release_is_created_as_a_prerelease_that_is_not_latest(tmp_path: Path) -> None:
    result, calls = _run(tmp_path, tag="cli-v0.7.0-beta.1", state="absent")

    assert result.returncode == 0, result.stderr
    create = calls[-1]
    assert create.startswith(
        "release create cli-v0.7.0-beta.1 --verify-tag --prerelease --latest=false"
    )


def test_an_existing_beta_release_not_marked_prerelease_is_marked(tmp_path: Path) -> None:
    result, calls = _run(tmp_path, tag="cli-v0.7.0-beta.1", state="stable")

    assert result.returncode == 0, result.stderr
    assert calls[-1] == "release edit cli-v0.7.0-beta.1 --prerelease --latest=false"


def test_an_existing_prerelease_is_left_alone(tmp_path: Path) -> None:
    result, calls = _run(tmp_path, tag="cli-v0.7.0-beta.1", state="prerelease")

    assert result.returncode == 0, result.stderr
    assert [call.split()[1] for call in calls] == ["view"]


@pytest.mark.parametrize("tag", ["cli-v0.7.0", "cli-v0.7.0-rc.1", "desktop-v0.7.0-beta.1"])
def test_anything_but_a_cli_beta_tag_is_refused_untouched(tmp_path: Path, tag: str) -> None:
    result, calls = _run(tmp_path, tag=tag, state="absent")

    assert result.returncode != 0
    assert "is not a CLI beta" in result.stderr
    assert calls == []
