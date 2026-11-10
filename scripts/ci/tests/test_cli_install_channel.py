"""`packages/cli/install.sh` installs the npm dist-tag GAIA_CHANNEL names, through every package manager.

Hermetic: PATH holds the coreutils the script needs plus a stub package manager
that records its argv and drops a gaia shim. No registry is contacted.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
INSTALL_SH = REPO_ROOT / "packages" / "cli" / "install.sh"

HOST_TOOLS = (
    "sh",
    "uname",
    "cat",
    "chmod",
    "dirname",
    "basename",
    "mktemp",
    "rm",
    "date",
    "tail",
    "grep",
)

# Stands in for npm / pnpm / bun: records argv, then installs a gaia shim.
PKG_MGR_STUB = """#!/bin/sh
[ "$1" = "--version" ] && { echo 1.0.0; exit 0; }
echo "$(basename "$0") $*" >> "$INSTALL_LOG"
bin_dir="$(dirname "$0")"
printf '#!/bin/sh\\n' > "$bin_dir/gaia"
chmod +x "$bin_dir/gaia"
"""

EXPECTED_COMMAND = {
    "npm": "npm install -g --ignore-scripts --no-fund --no-audit --loglevel=error @heygaia/cli@{channel}",
    "pnpm": "pnpm add -g @heygaia/cli@{channel}",
    "bun": "bun install -g --ignore-scripts @heygaia/cli@{channel}",
}


def _host(tmp_path: Path, pkg_mgr: str) -> tuple[dict[str, str], Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in HOST_TOOLS:
        real = shutil.which(tool)
        assert real, f"{tool} is needed to run install.sh"
        (bin_dir / tool).symlink_to(real)
    stub = bin_dir / pkg_mgr
    stub.write_text(PKG_MGR_STUB)
    stub.chmod(0o755)
    log = tmp_path / "install.log"
    env = {
        "PATH": str(bin_dir),
        "HOME": str(tmp_path),
        "INSTALL_LOG": str(log),
        "TERM": os.environ.get("TERM", "dumb"),
    }
    return env, log


def _run(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sh", str(INSTALL_SH)], capture_output=True, check=False, text=True, env=env
    )


@pytest.mark.parametrize("pkg_mgr", sorted(EXPECTED_COMMAND))
@pytest.mark.parametrize("channel", ["latest", "beta"])
def test_installs_the_named_channel(tmp_path: Path, pkg_mgr: str, channel: str) -> None:
    env, log = _host(tmp_path, pkg_mgr)
    env["GAIA_CHANNEL"] = channel

    result = _run(env)

    assert result.returncode == 0, result.stdout + result.stderr
    assert log.read_text().splitlines() == [EXPECTED_COMMAND[pkg_mgr].format(channel=channel)]


def test_no_channel_installs_latest(tmp_path: Path) -> None:
    env, log = _host(tmp_path, "npm")

    result = _run(env)

    assert result.returncode == 0, result.stdout + result.stderr
    assert log.read_text().splitlines() == [
        "npm install -g --ignore-scripts --no-fund --no-audit --loglevel=error @heygaia/cli@latest"
    ]


@pytest.mark.parametrize("channel", ["next", "Beta", "0.7.0-beta.1", "beta; rm -rf ~"])
def test_unknown_channel_is_refused_before_anything_installs(tmp_path: Path, channel: str) -> None:
    env, log = _host(tmp_path, "npm")
    env["GAIA_CHANNEL"] = channel

    result = _run(env)

    assert result.returncode == 1
    assert f"GAIA_CHANNEL must be 'latest' or 'beta', got '{channel}'" in result.stdout
    assert not log.exists()


@pytest.mark.parametrize("pkg_mgr", sorted(EXPECTED_COMMAND))
def test_a_tarball_override_installs_that_build_and_says_so(tmp_path: Path, pkg_mgr: str) -> None:
    env, log = _host(tmp_path, pkg_mgr)
    tarball = "http://192.168.139.1:8790/heygaia-cli-0.7.0-beta.4.tgz"
    env["GAIA_CLI_TARBALL"] = tarball

    result = _run(env)

    assert result.returncode == 0, result.stdout + result.stderr
    assert log.read_text().splitlines() == [
        EXPECTED_COMMAND[pkg_mgr].replace("@heygaia/cli@{channel}", tarball)
    ]
    warning = "  ! GAIA CLI from GAIA_CLI_TARBALL: heygaia-cli-0.7.0-beta.4.tgz\n"
    assert warning in result.stdout
    # One line on an 80-column terminal, however long the build's URL.
    assert len(warning.rstrip()) <= 80


@pytest.mark.parametrize(
    "tarball", ["@heygaia/cli@beta", "relative/cli.tgz", "http://host/cli.zip"]
)
def test_a_tarball_override_that_is_not_one_installs_nothing(tmp_path: Path, tarball: str) -> None:
    env, log = _host(tmp_path, "npm")
    env["GAIA_CLI_TARBALL"] = tarball

    result = _run(env)

    assert result.returncode == 1
    assert (
        "GAIA_CLI_TARBALL must be an http(s) URL or absolute path ending in .tgz" in result.stdout
    )
    assert not log.exists()
