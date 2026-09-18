"""`tools/gaia-connect/install.sh` is piped into a shell by strangers.

It is served at heygaia.io/connect.sh and run as
`curl -fsSL … | sh -s -- --token <code>`, so three things must hold no matter
what the network hands it: the asset name matches the release contract the CLI
publishes, a tampered binary is never written or executed, and every flag after
`sh -s --` reaches the tool untouched.

The script is exercised hermetically — a PATH shim serves a local "release"
directory in place of curl, and `uname` is shimmed per target.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
INSTALL_SH = REPO_ROOT / "tools" / "gaia-connect" / "install.sh"

CLI_TAG = "cli-v0.6.0"
SUMS_NAME = "gaia-connect-SHA256SUMS"

# The binary the fake release serves: echoes its argv so arg pass-through is
# observable, and prints a marker so we know the real thing ran.
FAKE_BINARY = """#!/usr/bin/env bash
echo "gaia-connect-ran: $*"
"""

# Stands in for curl. Maps the GitHub URLs the script uses onto files in
# $RELEASE_DIR; anything else 404s the way curl -f does.
CURL_SHIM = """#!/usr/bin/env bash
set -euo pipefail
url=""
dest=""
prev=""
for arg in "$@"; do
  case "$arg" in
    -*) ;;
    *) if [[ "$prev" == "-o" ]]; then dest="$arg"; else url="$arg"; fi ;;
  esac
  prev="$arg"
done
case "$url" in
  *api.github.com/repos/*/releases*) src="$RELEASE_DIR/releases.json" ;;
  *releases/download/*) src="$RELEASE_DIR/${url##*/download/}" ;;
  *) echo "curl shim: unexpected url $url" >&2; exit 22 ;;
esac
[[ -f "$src" ]] || exit 22
if [[ -n "$dest" ]]; then cp "$src" "$dest"; else cat "$src"; fi
"""

UNAME_SHIM = """#!/usr/bin/env bash
case "$1" in
  -s) echo "$FAKE_UNAME_S" ;;
  -m) echo "$FAKE_UNAME_M" ;;
  *) echo "$FAKE_UNAME_S" ;;
esac
"""


def _write_exec(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(0o755)


@pytest.fixture
def release(tmp_path: Path) -> Path:
    """Build a fake GitHub release: every asset, a real manifest, and a feed.

    The feed's newest entry is a desktop tag, so picking `latest` off it would be wrong.
    """
    root = tmp_path / "release" / CLI_TAG
    root.mkdir(parents=True)

    assets = [
        "gaia-connect-darwin-arm64",
        "gaia-connect-darwin-amd64",
        "gaia-connect-linux-amd64",
        "gaia-connect-linux-arm64",
    ]
    lines = []
    for asset in assets:
        target = root / asset
        _write_exec(target, FAKE_BINARY)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        lines.append(f"{digest}  {asset}")
    (root / SUMS_NAME).write_text("\n".join(lines) + "\n")

    (tmp_path / "release" / "releases.json").write_text(
        json.dumps(
            [
                {"tag_name": "desktop-v9.9.9"},
                {"tag_name": CLI_TAG},
                {"tag_name": "cli-v0.5.0"},
            ]
        )
    )
    return tmp_path / "release"


@dataclass(frozen=True)
class _Installer:
    """Runs install.sh with curl and uname shimmed onto PATH and a throwaway HOME."""

    home: Path
    bin_dir: Path
    release: Path

    def __call__(
        self,
        *args: str,
        uname_s: str = "Darwin",
        uname_m: str = "arm64",
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        real_path = os.environ["PATH"]
        return subprocess.run(
            ["sh", str(INSTALL_SH), *args],
            capture_output=True,
            check=False,
            text=True,
            env={
                "PATH": f"{self.bin_dir}:{real_path}",
                "HOME": str(self.home),
                "RELEASE_DIR": str(self.release),
                "FAKE_UNAME_S": uname_s,
                "FAKE_UNAME_M": uname_m,
                **(env or {}),
            },
        )


@pytest.fixture
def run(tmp_path: Path, release: Path) -> _Installer:
    bin_dir = tmp_path / "shims"
    bin_dir.mkdir()
    _write_exec(bin_dir / "curl", CURL_SHIM)
    _write_exec(bin_dir / "uname", UNAME_SHIM)
    home = tmp_path / "home"
    home.mkdir()
    return _Installer(home=home, bin_dir=bin_dir, release=release)


def _installed(home: Path) -> list[Path]:
    return sorted((home / ".gaia" / "bin").glob("*"))


def test_darwin_arm64_installs_and_runs_with_args(run) -> None:
    result = run("--token", "CODE", "--api", "http://localhost:8510")
    assert result.returncode == 0, result.stderr
    assert "gaia-connect-ran: --token CODE --api http://localhost:8510" in result.stdout
    assert _installed(run.home) == [run.home / ".gaia" / "bin" / "gaia-connect-0.6.0"]


def test_linux_amd64_picks_the_amd64_asset(run, release: Path) -> None:
    # Distinguish the asset actually used by giving this one a unique payload.
    asset = release / CLI_TAG / "gaia-connect-linux-amd64"
    _write_exec(asset, '#!/usr/bin/env bash\necho "linux-amd64 binary"\n')
    digest = hashlib.sha256(asset.read_bytes()).hexdigest()
    sums = release / CLI_TAG / SUMS_NAME
    sums.write_text(
        "\n".join(
            f"{digest}  gaia-connect-linux-amd64"
            if line.endswith("gaia-connect-linux-amd64")
            else line
            for line in sums.read_text().splitlines()
        )
        + "\n"
    )

    result = run(uname_s="Linux", uname_m="x86_64")
    assert result.returncode == 0, result.stderr
    assert "linux-amd64 binary" in result.stdout


def test_newest_cli_tag_wins_over_a_newer_desktop_tag(run) -> None:
    result = run()
    assert result.returncode == 0, result.stderr
    # 9.9.9 is newer but is a desktop release; 0.5.0 is an older cli release.
    assert (run.home / ".gaia" / "bin" / "gaia-connect-0.6.0").exists()
    assert not (run.home / ".gaia" / "bin" / "gaia-connect-9.9.9").exists()


def test_version_env_pins_the_tag(run, release: Path) -> None:
    shutil.copytree(release / CLI_TAG, release / "cli-v0.5.0")
    result = run(env={"GAIA_CONNECT_VERSION": "0.5.0"})
    assert result.returncode == 0, result.stderr
    assert (run.home / ".gaia" / "bin" / "gaia-connect-0.5.0").exists()


def test_tampered_binary_is_rejected_and_nothing_is_installed(run, release: Path) -> None:
    _write_exec(
        release / CLI_TAG / "gaia-connect-darwin-arm64",
        '#!/usr/bin/env bash\necho "PWNED"\n',
    )
    result = run("--token", "CODE")
    assert result.returncode != 0
    assert "Checksum mismatch" in result.stderr
    assert "PWNED" not in result.stdout
    assert not (run.home / ".gaia" / "bin").exists()


def test_install_only_does_not_run_the_binary(run) -> None:
    result = run(env={"GAIA_CONNECT_INSTALL_ONLY": "1"})
    assert result.returncode == 0, result.stderr
    assert "gaia-connect-ran" not in result.stdout
    assert result.stdout.strip().endswith("gaia-connect-0.6.0")


def test_windows_points_at_the_npx_path(run) -> None:
    result = run(uname_s="MINGW64_NT-10.0", uname_m="x86_64")
    assert result.returncode != 0
    assert "npx @heygaia/cli connect" in result.stderr


def test_unsupported_arch_names_the_supported_targets(run) -> None:
    result = run(uname_s="Linux", uname_m="riscv64")
    assert result.returncode != 0
    assert "not available for linux/unknown" in result.stderr
    assert "linux/amd64" in result.stderr
