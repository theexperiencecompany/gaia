"""release.mjs sends X.Y.Z to npm's latest and X.Y.Z-beta.N to beta, and nothing else is a CLI release.

A beta is cut by hand on top of the last stable release, so package.json names
the beta while the release-please manifest still names that stable version.
npm is a PATH stub that reports which versions are already published.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
RELEASE_MJS = REPO_ROOT / "scripts" / "ci" / "release.mjs"

NPM_STUB = """#!/bin/sh
cat "$NPM_VERSIONS"
"""


def _workspace(
    tmp_path: Path, *, package: str, manifest: str, published: tuple[str, ...] = ("0.6.0",)
) -> Path:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / ".release-please-manifest.json").write_text(
        json.dumps({"packages/cli": manifest})
    )
    (tmp_path / "config" / "release-please-config.json").write_text(
        json.dumps({"packages": {"packages/cli": {"release-type": "node"}}})
    )
    (tmp_path / "packages" / "cli").mkdir(parents=True)
    (tmp_path / "packages" / "cli" / "package.json").write_text(
        json.dumps({"name": "@heygaia/cli", "version": package})
    )
    (tmp_path / "bin").mkdir()
    npm = tmp_path / "bin" / "npm"
    npm.write_text(NPM_STUB)
    npm.chmod(0o755)
    (tmp_path / "npm-versions.json").write_text(json.dumps(list(published)))
    return tmp_path


def _release_mjs(workspace: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.update(
        PATH=f"{workspace / 'bin'}{os.pathsep}{env['PATH']}",
        NPM_VERSIONS=str(workspace / "npm-versions.json"),
        GITHUB_OUTPUT=str(workspace / "github-output.txt"),
    )
    return subprocess.run(
        ["node", str(RELEASE_MJS), *args],
        cwd=workspace,
        check=False,
        env=env,
        capture_output=True,
        text=True,
    )


def _verify(workspace: Path, version: str) -> subprocess.CompletedProcess[str]:
    return _release_mjs(workspace, "verify-cli", "--tag", f"cli-v{version}", "--version", version)


def _outputs(workspace: Path) -> dict[str, str]:
    lines = (workspace / "github-output.txt").read_text().splitlines()
    return dict(line.split("=", 1) for line in lines)


def test_a_stable_release_publishes_to_latest(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path, package="0.7.0", manifest="0.7.0")

    result = _verify(workspace, "0.7.0")

    assert result.returncode == 0, result.stderr
    outputs = _outputs(workspace)
    assert outputs["npm_dist_tag"] == "latest"
    assert outputs["prerelease"] == "false"
    assert outputs["should_publish"] == "true"


def test_a_beta_after_the_last_stable_publishes_to_beta(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path, package="0.7.0-beta.1", manifest="0.6.0")

    result = _verify(workspace, "0.7.0-beta.1")

    assert result.returncode == 0, result.stderr
    outputs = _outputs(workspace)
    assert outputs["npm_dist_tag"] == "beta"
    assert outputs["prerelease"] == "true"
    assert outputs["should_publish"] == "true"


@pytest.mark.parametrize("beta", ["0.6.0-beta.1", "0.5.9-beta.3"])
def test_a_beta_that_is_not_ahead_of_the_last_stable_is_refused(tmp_path: Path, beta: str) -> None:
    workspace = _workspace(tmp_path, package=beta, manifest="0.6.0")

    result = _verify(workspace, beta)

    assert result.returncode == 1
    assert "must be a beta of a release after the last stable one" in result.stderr


@pytest.mark.parametrize("version", ["0.7.0-rc.1", "0.7.0-beta", "0.7.0-beta.1.2", "0.7.0-next.1"])
def test_any_other_prerelease_is_never_published(tmp_path: Path, version: str) -> None:
    workspace = _workspace(tmp_path, package=version, manifest="0.6.0")

    result = _verify(workspace, version)

    assert result.returncode == 1
    assert "must be X.Y.Z (npm latest) or X.Y.Z-beta.N (npm beta)" in result.stderr


def test_a_tag_naming_another_beta_is_refused(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path, package="0.7.0-beta.2", manifest="0.6.0")

    result = _release_mjs(
        workspace, "verify-cli", "--tag", "cli-v0.7.0-beta.1", "--version", "0.7.0-beta.2"
    )

    assert result.returncode == 1
    assert "does not match tag-derived version" in result.stderr


def test_a_published_beta_is_skipped_not_republished(tmp_path: Path) -> None:
    workspace = _workspace(
        tmp_path, package="0.7.0-beta.1", manifest="0.6.0", published=("0.6.0", "0.7.0-beta.1")
    )

    result = _verify(workspace, "0.7.0-beta.1")

    assert result.returncode == 0, result.stderr
    assert _outputs(workspace)["should_publish"] == "false"


def test_the_manifest_check_accepts_a_cli_beta_ahead_of_the_last_stable(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path, package="0.7.0-beta.1", manifest="0.6.0")

    result = _release_mjs(workspace, "validate-manifest")

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("package", ["0.6.1", "0.6.0-beta.1"])
def test_the_manifest_check_still_refuses_any_other_drift(tmp_path: Path, package: str) -> None:
    workspace = _workspace(tmp_path, package=package, manifest="0.6.0")

    result = _release_mjs(workspace, "validate-manifest")

    assert result.returncode == 1
    assert "Version mismatch" in result.stderr
