"""`packages/cli/install.sh` on a fresh server: no Node yet is the expected path, not a warning.

Hermetic: PATH holds only the coreutils the script needs plus a curl shim that
serves a fake nvm, whose `nvm install` drops node/npm shims and whose
`npm install -g` drops a gaia shim. Real nvm, Node and npm are never touched.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
INSTALL_SH = REPO_ROOT / "packages" / "cli" / "install.sh"

HOST_TOOLS = ("sh", "bash", "uname", "mkdir", "cat", "chmod", "mktemp", "tail", "rm")

NVM_NOISE = "=> Appending nvm source string to /home/u/.bashrc"
NVM_DOWNLOAD_NOISE = (
    "######################################################################## 100.0%"
)
NPM_NOISE = ("npm warn ERESOLVE overriding peer dependency", "added 194 packages in 9s")
NPM_FAILURE_TAIL = "npm error 404 Not Found - GET https://registry.npmjs.org/@heygaia%2fcli"
GET_STARTED_UP = "  \033[0;32mgaia up\033[0m"

# What `curl …/nvm-sh/nvm/…/install.sh` returns: a chatty nvm whose install puts
# node and npm on PATH, and a chatty npm whose global install puts gaia there.
FAKE_NVM_INSTALLER = rf"""
echo '{NVM_NOISE}'
mkdir -p "$HOME/.nvm/bin"
cat > "$HOME/.nvm/nvm.sh" <<'NVM'
nvm() {{
  echo '{NVM_DOWNLOAD_NOISE}'
  printf '#!/bin/sh\necho v22.0.0\n' > "$NVM_DIR/bin/node"
  printf '#!/bin/sh\necho "{NPM_NOISE[0]}"\necho "{NPM_NOISE[1]}"\nprintf "#!/bin/sh\\n" > "$NVM_DIR/bin/gaia"; chmod +x "$NVM_DIR/bin/gaia"\n' > "$NVM_DIR/bin/npm"
  chmod +x "$NVM_DIR/bin/node" "$NVM_DIR/bin/npm"
  PATH="$NVM_DIR/bin:$PATH"
}}
NVM
"""

CURL_SHIM = f"""#!/bin/sh
cat <<'INSTALLER'
{FAKE_NVM_INSTALLER}
INSTALLER
"""


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(0o755)


def _fake_npm(prefix: Path, install_body: str) -> str:
    return f"""#!/bin/sh
case "$1" in
  --version) echo 10.0.0 ;;
  config) echo '{prefix}' ;;
  install)
{install_body}
    ;;
esac
"""


def _gaia_installer(bin_dir: Path) -> str:
    return (
        f'    echo "{NPM_NOISE[0]}"; echo "{NPM_NOISE[1]}"\n'
        f"    mkdir -p '{bin_dir}'\n"
        f"    printf '#!/bin/sh\\n' > '{bin_dir}/gaia'; chmod +x '{bin_dir}/gaia'"
    )


def _run(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sh", str(INSTALL_SH)], capture_output=True, check=False, text=True, env=env
    )


@pytest.fixture
def fresh_server(tmp_path: Path) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in HOST_TOOLS:
        real = shutil.which(tool)
        assert real, f"{tool} is needed to run install.sh"
        (bin_dir / tool).symlink_to(real)
    _write_executable(bin_dir / "curl", CURL_SHIM)
    home = tmp_path / "home"
    home.mkdir()
    tmp = tmp_path / "tmp"
    tmp.mkdir()
    return {
        "PATH": str(bin_dir),
        "HOME": str(home),
        "TMPDIR": str(tmp),
        "TERM": os.environ.get("TERM", "dumb"),
    }


def test_no_node_yet_is_info_and_says_nvm_comes_next(fresh_server: dict[str, str]) -> None:
    result = _run(fresh_server)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "No supported package manager" not in result.stdout
    assert (
        "[info]\033[0m No Node.js package manager yet (npm, pnpm, or bun), "
        "so installing Node.js via nvm..."
    ) in result.stdout
    assert "Node.js v22.0.0 installed\n" in result.stdout


def test_nvm_install_prints_a_command_that_loads_nvm_then_runs_gaia_up(
    fresh_server: dict[str, str],
) -> None:
    result = _run(fresh_server)

    assert result.returncode == 0, result.stdout + result.stderr
    nvm_dir = Path(fresh_server["HOME"]) / ".nvm"
    assert f'. "{nvm_dir}/nvm.sh" && gaia up' in result.stdout
    assert GET_STARTED_UP not in result.stdout


def test_install_output_of_nvm_and_npm_is_hidden_on_success(
    fresh_server: dict[str, str],
) -> None:
    result = _run(fresh_server)

    assert result.returncode == 0, result.stdout + result.stderr
    output = result.stdout + result.stderr
    for noise in (NVM_NOISE, NVM_DOWNLOAD_NOISE, *NPM_NOISE):
        assert noise not in output
    assert not list(Path(fresh_server["TMPDIR"]).iterdir())


def test_gaia_already_on_path_keeps_the_get_started_list(
    fresh_server: dict[str, str], tmp_path: Path
) -> None:
    bin_dir = Path(fresh_server["PATH"])
    _write_executable(bin_dir / "npm", _fake_npm(tmp_path, _gaia_installer(bin_dir)))

    result = _run(fresh_server)

    assert result.returncode == 0, result.stdout + result.stderr
    assert GET_STARTED_UP in result.stdout
    assert "gaia status" in result.stdout
    assert "cannot find gaia" not in result.stdout


def test_npm_prefix_off_path_prints_the_path_fix_then_gaia_up(
    fresh_server: dict[str, str], tmp_path: Path
) -> None:
    prefix = tmp_path / "npm-global"
    _write_executable(
        Path(fresh_server["PATH"]) / "npm", _fake_npm(prefix, _gaia_installer(prefix / "bin"))
    )

    result = _run(fresh_server)

    assert result.returncode == 0, result.stdout + result.stderr
    assert f'export PATH="{prefix}/bin:$PATH" && gaia up' in result.stdout
    assert GET_STARTED_UP not in result.stdout


def test_failing_npm_shows_its_output_tail_and_log_path_and_exits_non_zero(
    fresh_server: dict[str, str], tmp_path: Path
) -> None:
    filler = "\n".join(f"    echo 'npm http fetch line {n}'" for n in range(40))
    failing = f"{filler}\n    echo '{NPM_FAILURE_TAIL}'\n    exit 1"
    _write_executable(Path(fresh_server["PATH"]) / "npm", _fake_npm(tmp_path, failing))

    result = _run(fresh_server)

    assert result.returncode != 0
    assert NPM_FAILURE_TAIL in result.stdout
    assert "npm http fetch line 39" in result.stdout
    assert "npm http fetch line 0\n" not in result.stdout
    match = re.search(r"Full log: (\S+)", result.stdout)
    assert match, result.stdout
    assert NPM_FAILURE_TAIL in Path(match.group(1)).read_text()
