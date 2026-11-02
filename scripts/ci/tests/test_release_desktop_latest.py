"""release.sh desktop-tag / mark-desktop-latest: the desktop release electron-updater resolves.

The newest desktop tag was searched for among the last 50 GitHub releases;
desktop ships rarely, so once 50 others landed the search came back empty and
the step printed "skipping". The version comes from release-please's manifest.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

REPO_ROOT = Path(__file__).resolve().parents[3]
RELEASE_SH = REPO_ROOT / "scripts" / "ci" / "release.sh"
DESKTOP_TAG = (
    "desktop-v"
    + json.loads((REPO_ROOT / "config/.release-please-manifest.json").read_text())["apps/desktop"]
)

# Logs every call; `gh release view --json assets` answers from $ASSETS.
GH_STUB = """\\
#!/usr/bin/env bash
echo "$*" >> "$REC"
if [ "$1 $2" = "release view" ]; then printf '%s\\n' $ASSETS; fi
"""


def _run(tmp_path: Path, sub: str, assets: str = "") -> tuple[str, list[str]]:
    stub = tmp_path / "gh"
    stub.write_text(GH_STUB)
    stub.chmod(0o755)
    rec = tmp_path / "calls"
    rec.write_text("")
    out = subprocess.run(
        ["bash", str(RELEASE_SH), sub],
        env={
            **os.environ,
            "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
            "REC": str(rec),
            "ASSETS": assets,
            "GITHUB_REPOSITORY": "o/r",
        },
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return out.strip(), rec.read_text().splitlines()


def test_the_desktop_tag_is_the_manifest_version(tmp_path: Path) -> None:
    out, calls = _run(tmp_path, "desktop-tag")
    assert out == DESKTOP_TAG
    assert calls == []


def test_a_desktop_release_with_its_updater_files_is_marked_latest(tmp_path: Path) -> None:
    _, calls = _run(tmp_path, "mark-desktop-latest", "latest.yml latest-mac.yml app.dmg")
    assert any(c.startswith(f"release edit {DESKTOP_TAG}") and "--latest" in c for c in calls)


def test_a_desktop_release_without_its_installers_yet_is_not_marked(tmp_path: Path) -> None:
    """electron-updater 404s on a Latest with no latest-*.yml; desktop-release marks it after the upload."""
    _, calls = _run(tmp_path, "mark-desktop-latest", "")
    assert not any(c.startswith("release edit") for c in calls)
