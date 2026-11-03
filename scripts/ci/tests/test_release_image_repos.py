"""lib/image-repos.sh names exactly the repos nx releases, and the bots the CLI self-hosts.

The release and deploy scripts are bash in jobs with no node, so they read
these arrays rather than nx. A bot added to an nx release group but not here
was never pinned or re-pointed at deploy; one added to the CLI's SELFHOST_BOTS
but not here was never tagged for `gaia bots add` to pull.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
IMAGE_REPOS = REPO_ROOT / "scripts" / "ci" / "lib" / "image-repos.sh"


def _array(name: str) -> list[str]:
    out = subprocess.run(
        ["bash", "-c", f'source "$0"; printf "%s\\n" "${{{name}[@]}}"', str(IMAGE_REPOS)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return out.split()


def _released_repos(tag: str) -> list[str]:
    """Return the GHCR repo of every project carrying the release group's tag, as nx.json selects them."""
    repos = []
    for path in REPO_ROOT.glob("apps/**/project.json"):
        if "node_modules" in path.parts:
            continue
        project = json.loads(path.read_text())
        if tag in project.get("tags", []):
            repos.append(project["release"]["docker"]["repositoryName"].split("/", 1)[1])
    return sorted(repos)


@pytest.mark.parametrize(
    ("array", "tag"), [("APPS_IMAGE_REPOS", "release:apps"), ("BOTS_IMAGE_REPOS", "release:bots")]
)
def test_an_image_group_is_the_nx_release_group(array: str, tag: str) -> None:
    groups = json.loads((REPO_ROOT / "nx.json").read_text())["release"]["groups"]
    assert f"tag:{tag}" in {p for g in groups.values() for p in g["projects"]}
    assert sorted(_array(array)) == _released_repos(tag)


def test_the_self_host_bots_are_the_clis() -> None:
    source = (REPO_ROOT / "packages" / "cli" / "src" / "lib" / "bots.ts").read_text()
    match = re.search(r"SELFHOST_BOTS = \[([^\]]*)\]", source)
    assert match, "SELFHOST_BOTS not found in packages/cli/src/lib/bots.ts"
    cli = sorted(f"gaia-bot-{b}" for b in re.findall(r'"([a-z]+)"', match.group(1)))
    assert sorted(_array("SELFHOST_BOT_IMAGE_REPOS")) == cli
