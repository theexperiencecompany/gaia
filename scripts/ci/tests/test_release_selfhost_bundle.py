"""`release.sh selfhost-bundle` builds the files a self-host install runs and attaches them to the release.

`gaia up` and `gaia update` download gaia-selfhost-<version>.tar.gz instead of
cloning the repo, so the bundle must carry every file the self-host compose
files read from disk, a manifest naming them, and a checksum the CLI verifies.
gh is a PATH stub that logs every call.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tarfile

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
RELEASE_SH = REPO_ROOT / "scripts" / "ci" / "release.sh"
MANIFEST = "gaia-selfhost.json"

GH_STUB = """#!/usr/bin/env bash
set -euo pipefail
echo "$*" >> "$GH_CALLS"
"""


def _run(
    tmp_path: Path, **env_vars: str
) -> tuple[subprocess.CompletedProcess[str], list[str], Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    gh = bin_dir / "gh"
    gh.write_text(GH_STUB)
    gh.chmod(0o755)
    calls = tmp_path / "gh-calls.txt"
    calls.write_text("")
    out_dir = tmp_path / "out"
    env = {k: v for k, v in os.environ.items() if k not in {"RELEASE_TAG", "DRY_RUN"}}
    env.update(
        PATH=f"{bin_dir}{os.pathsep}{env['PATH']}",
        GH_CALLS=str(calls),
        GH_TOKEN="t0ken",
        OUT_DIR=str(out_dir),
        **env_vars,
    )
    result = subprocess.run(
        ["bash", str(RELEASE_SH), "selfhost-bundle"],
        check=False,
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    return result, calls.read_text().splitlines(), out_dir


def _members(bundle: Path) -> dict[str, bytes]:
    members: dict[str, bytes] = {}
    with tarfile.open(bundle) as archive:
        for member in archive.getmembers():
            content = archive.extractfile(member) if member.isfile() else None
            if content is not None:
                members[member.name] = content.read()
    return members


def test_the_bundle_holds_the_manifest_and_the_files_it_names(tmp_path: Path) -> None:
    result, calls, out_dir = _run(tmp_path, VERSION="0.7.0-beta.4")

    assert result.returncode == 0, result.stderr
    assert calls == []
    members = _members(out_dir / "gaia-selfhost-0.7.0-beta.4.tar.gz")
    manifest = json.loads(members[MANIFEST])
    assert manifest["version"] == "v0.7.0-beta.4"
    assert sorted(members) == manifest["files"]
    assert "packages/cli/selfhost/docker-compose.selfhost.yml" in members
    assert "packages/cli/selfhost/Caddyfile" in members
    assert (
        members["packages/cli/selfhost/docker-compose.selfhost.yml"]
        == (REPO_ROOT / "packages/cli/selfhost/docker-compose.selfhost.yml").read_bytes()
    )
    # Building from source needs the whole tree; a bundle install never builds.
    assert "packages/cli/selfhost/docker-compose.build.yml" not in members
    assert not any(".env" in Path(name).name for name in members)


def test_the_checksum_file_verifies_the_bundle(tmp_path: Path) -> None:
    result, _, out_dir = _run(tmp_path, VERSION="0.7.0")

    assert result.returncode == 0, result.stderr
    sums = (out_dir / "gaia-selfhost-0.7.0.tar.gz.sha256").read_text()
    assert sums.split()[1] == "gaia-selfhost-0.7.0.tar.gz"
    check = subprocess.run(
        ["sha256sum", "-c", "gaia-selfhost-0.7.0.tar.gz.sha256"],
        cwd=out_dir,
        check=False,
        capture_output=True,
        text=True,
    )
    assert check.returncode == 0, check.stdout + check.stderr


def _referenced_files(compose_file: str, text: str) -> set[str]:
    """Every file a compose file reads from disk, relative to the repo root (env files aside)."""
    base = Path(compose_file).parent
    doc = yaml.safe_load(text) or {}
    found: set[str] = set()
    for service in (doc.get("services") or {}).values():
        extends = service.get("extends") or {}
        if "file" in extends:
            found.add(os.path.normpath(base / extends["file"]))
        for volume in service.get("volumes") or []:
            source = (
                volume.split(":", 1)[0] if isinstance(volume, str) else volume.get("source", "")
            )
            if source.startswith("."):
                found.add(os.path.normpath(base / source))
    return found


def test_every_file_the_bundled_compose_files_read_is_in_the_bundle(tmp_path: Path) -> None:
    result, _, out_dir = _run(tmp_path, VERSION="0.7.0")

    assert result.returncode == 0, result.stderr
    members = _members(out_dir / "gaia-selfhost-0.7.0.tar.gz")
    referenced: set[str] = set()
    for name, content in members.items():
        if name.endswith(".yml") and Path(name).name.startswith("docker-compose."):
            referenced |= _referenced_files(name, content.decode())
    assert referenced, "the compose files reference no files: the parser is broken"
    assert referenced - set(members) == set()


def test_a_release_upload_attaches_the_bundle_and_its_checksum(tmp_path: Path) -> None:
    result, calls, _ = _run(tmp_path, VERSION="0.7.0", RELEASE_TAG="cli-v0.7.0")

    assert result.returncode == 0, result.stderr
    assert calls == [
        "release upload cli-v0.7.0 gaia-selfhost-0.7.0.tar.gz gaia-selfhost-0.7.0.tar.gz.sha256 --clobber"
    ]


def test_a_dry_run_builds_and_names_the_upload_without_making_it(tmp_path: Path) -> None:
    result, calls, out_dir = _run(tmp_path, VERSION="0.7.0", RELEASE_TAG="cli-v0.7.0", DRY_RUN="1")

    assert result.returncode == 0, result.stderr
    assert calls == []
    assert "dry run" in result.stdout
    assert (out_dir / "gaia-selfhost-0.7.0.tar.gz").exists()


@pytest.mark.parametrize(
    ("version", "tag"),
    [("0.7.0", "cli-v0.6.9"), ("latest", ""), ("0.7", "")],
)
def test_a_version_that_is_not_the_release_publishes_nothing(
    tmp_path: Path, version: str, tag: str
) -> None:
    env = {"VERSION": version, **({"RELEASE_TAG": tag} if tag else {})}
    result, calls, out_dir = _run(tmp_path, **env)

    assert result.returncode != 0
    assert calls == []
    assert not list(out_dir.glob("*.tar.gz")) if out_dir.exists() else True
