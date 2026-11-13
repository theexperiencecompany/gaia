"""`release.sh connect-binaries` publishes a contract, not just some files.

The CLI's `gaia connect` downloads these assets from the `cli-v<version>`
release BY EXACT NAME and verifies them against `gaia-connect-SHA256SUMS` in
standard `sha256sum` format. Rename an asset, drop a target, or change the
manifest layout and every already-released CLI starts 404ing — with a green
release run, because the upload itself succeeded.

So the names and the manifest format are asserted here, where a change to them
has to be made deliberately and a reviewer sees it.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
RELEASE_SH = REPO_ROOT / "scripts" / "ci" / "release.sh"

# The published contract. Kept literal (not derived from a GOOS/GOARCH loop) so
# the test fails when the script's target list changes rather than following it.
EXPECTED_ASSETS = [
    "gaia-connect-darwin-arm64",
    "gaia-connect-darwin-amd64",
    "gaia-connect-linux-amd64",
    "gaia-connect-linux-arm64",
    "gaia-connect-windows-amd64.exe",
]
SUMS_NAME = "gaia-connect-SHA256SUMS"
SUMS_LINE = re.compile(r"^([0-9a-f]{64})  (\S+)$")

GO_STUB = """#!/usr/bin/env bash
# Stands in for the toolchain: honours -o <path> and writes distinguishable
# bytes so the manifest's digests are real and differ per target.
set -euo pipefail
out=""
prev=""
for arg in "$@"; do
  if [[ "$prev" == "-o" ]]; then out="$arg"; fi
  prev="$arg"
done
[[ -n "$out" ]] || { echo "go stub: no -o" >&2; exit 1; }
printf 'fake-binary %s %s\\n' "${GOOS:-}" "${GOARCH:-}" > "$out"
chmod +x "$out"
"""

GH_STUB = """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$@" >> "$GH_CALLS"
"""

SHA256SUM_SHIM = """#!/usr/bin/env bash
exec shasum -a 256 "$@"
"""


def _write_stub(directory: Path, name: str, body: str) -> None:
    path = directory / name
    path.write_text(body)
    path.chmod(0o755)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Create a throwaway repo root with a gaia-connect module and stubbed externals."""
    (tmp_path / "tools" / "gaia-connect").mkdir(parents=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_stub(bin_dir, "go", GO_STUB)
    _write_stub(bin_dir, "gh", GH_STUB)
    # macOS has no GNU sha256sum; shasum -a 256 prints the identical
    # "<hex>  <name>" format, so the assertion below stays honest.
    if shutil.which("sha256sum") is None:
        _write_stub(bin_dir, "sha256sum", SHA256SUM_SHIM)
    return tmp_path


def _run(
    workspace: Path, *, tag: str, token: str | None = "t0ken"
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PATH"] = f"{workspace / 'bin'}{os.pathsep}{env['PATH']}"
    env["RELEASE_TAG"] = tag
    env["GH_CALLS"] = str(workspace / "gh-calls.txt")
    env.pop("GITHUB_STEP_SUMMARY", None)
    if token is None:
        env.pop("GH_TOKEN", None)
    else:
        env["GH_TOKEN"] = token
    return subprocess.run(
        ["bash", str(RELEASE_SH), "connect-binaries"],
        cwd=workspace,
        check=False,
        env=env,
        capture_output=True,
        text=True,
    )


def test_every_published_target_is_built_and_uploaded(workspace: Path) -> None:
    result = _run(workspace, tag="cli-v1.2.3")
    assert result.returncode == 0, result.stderr

    out_dir = workspace / "tools" / "gaia-connect" / "dist"
    built = sorted(p.name for p in out_dir.iterdir())
    assert built == sorted([*EXPECTED_ASSETS, SUMS_NAME])

    calls = (workspace / "gh-calls.txt").read_text().splitlines()
    assert calls[:3] == ["release", "upload", "cli-v1.2.3"]
    assert calls[3:] == [*EXPECTED_ASSETS, SUMS_NAME, "--clobber"]


def test_the_manifest_is_standard_sha256sum_format(workspace: Path) -> None:
    assert _run(workspace, tag="cli-v1.2.3").returncode == 0

    sums = (workspace / "tools" / "gaia-connect" / "dist" / SUMS_NAME).read_text()
    lines = sums.splitlines()
    assert len(lines) == len(EXPECTED_ASSETS)

    digests, names = [], []
    for line in lines:
        match = SUMS_LINE.match(line)
        assert match, f"not sha256sum format: {line!r}"
        digests.append(match.group(1))
        names.append(match.group(2))

    # Bare asset names, never a path — the CLI resolves them against the release.
    assert names == EXPECTED_ASSETS
    # A per-target digest, not one value copied five times.
    assert len(set(digests)) == len(digests)


def test_the_cross_check_builds_every_published_target_and_publishes_nothing(
    workspace: Path,
) -> None:
    """The pre-merge lane must compile exactly the release's targets, and never touch a release."""
    env = dict(os.environ)
    env["PATH"] = f"{workspace / 'bin'}{os.pathsep}{env['PATH']}"
    env["GH_CALLS"] = str(workspace / "gh-calls.txt")
    env.pop("GITHUB_STEP_SUMMARY", None)
    env.pop("GH_TOKEN", None)
    env.pop("RELEASE_TAG", None)

    result = subprocess.run(
        ["bash", str(RELEASE_SH), "connect-cross-check"],
        cwd=workspace,
        check=False,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    built = [
        line.removeprefix("building ")
        for line in result.stdout.splitlines()
        if line.startswith("building ")
    ]
    assert built == EXPECTED_ASSETS
    assert not (workspace / "gh-calls.txt").exists()  # no upload, no release lookup
    assert not (workspace / "tools" / "gaia-connect" / "dist").exists()


def test_a_tag_that_is_not_a_cli_release_is_refused(workspace: Path) -> None:
    # Uploading to the wrong release is worse than not uploading: the assets
    # land somewhere nobody looks and the real release stays empty.
    result = _run(workspace, tag="desktop-v1.2.3")
    assert result.returncode != 0
    assert "cli-v<version>" in result.stderr
    assert not (workspace / "gh-calls.txt").exists()


def test_a_missing_token_fails_before_building(workspace: Path) -> None:
    result = _run(workspace, tag="cli-v1.2.3", token=None)
    assert result.returncode != 0
    assert not (workspace / "tools" / "gaia-connect" / "dist").exists()
