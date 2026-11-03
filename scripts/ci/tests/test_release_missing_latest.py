"""release.sh missing-latest: which image groups have no :latest in GHCR yet.

build.yml forces a group's build when it does (a first-time bootstrap). The
repo names come from lib/image-repos.sh, the list every other release step
reads; build.yml used to keep its own copy of them.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

RELEASE_SH = Path(__file__).resolve().parents[1] / "release.sh"

# `docker manifest inspect <ref>` fails for the refs listed in $MISSING.
DOCKER_STUB = """\
#!/usr/bin/env bash
[ "$1 $2" = "manifest inspect" ] || { echo "docker stub: unexpected $*" >&2; exit 1; }
case " $MISSING " in *" $3 "*) exit 1 ;; esac
"""


def _missing(tmp_path: Path, *refs: str) -> list[str]:
    stub = tmp_path / "docker"
    stub.write_text(DOCKER_STUB)
    stub.chmod(0o755)
    out = subprocess.run(
        ["bash", str(RELEASE_SH), "missing-latest"],
        env={
            **os.environ,
            "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
            "MISSING": " ".join(refs),
        },
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return out.split()


def test_every_image_present_misses_no_group(tmp_path: Path) -> None:
    assert _missing(tmp_path) == []


def test_one_missing_bot_image_names_the_bots_group(tmp_path: Path) -> None:
    assert _missing(tmp_path, "ghcr.io/theexperiencecompany/gaia-bot-imessage:latest") == ["bots"]


def test_a_missing_voice_agent_image_names_the_apps_group(tmp_path: Path) -> None:
    assert _missing(tmp_path, "ghcr.io/theexperiencecompany/gaia-voice-agent:latest") == ["apps"]
