"""`packages/cli/install.sh` on a fresh server: no Node yet is the expected path, not a warning.

Hermetic: PATH holds only the coreutils the script needs plus a curl shim that
serves a fake nvm, whose `nvm install` drops node/npm shims and whose
`npm install -g` drops a gaia shim. Real nvm, Node and npm are never touched.
"""

from __future__ import annotations

import os
from pathlib import Path
import pty
import re
import select
import shutil
import signal
import subprocess
import time

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
INSTALL_SH = REPO_ROOT / "packages" / "cli" / "install.sh"

HOST_TOOLS = (
    "sh",
    "bash",
    "uname",
    "mkdir",
    "cat",
    "chmod",
    "mktemp",
    "tail",
    "rm",
    "date",
    "sed",
    "grep",
    "sleep",
    "du",
    "cut",
    "tr",
    "wc",
)

NVM_NOISE = "=> Appending nvm source string to /home/u/.bashrc"
NVM_DOWNLOAD_NOISE = (
    "######################################################################## 100.0%"
)
NODE_DOWNLOAD_HALFWAY = "####################                     45.0%"
NPM_NOISE = ("npm warn ERESOLVE overriding peer dependency", "added 194 packages in 9s")
NPM_FAILURE_TAIL = "npm error 404 Not Found - GET https://registry.npmjs.org/@heygaia%2fcli"
GET_STARTED_UP = "Next, run:  gaia up\n"

# What `curl …/nvm-sh/nvm/…/install.sh` returns: a chatty nvm whose install puts
# node and npm on PATH, and a chatty npm whose global install puts gaia there.
FAKE_NVM_INSTALLER = rf"""
echo '{NVM_NOISE}'
mkdir -p "$HOME/.nvm/bin"
cat > "$HOME/.nvm/nvm.sh" <<'NVM'
nvm() {{
  echo 'Downloading https://nodejs.org/dist/v22.0.0/node-v22.0.0-linux-x64.tar.xz...'
  printf '\r%s' '{NODE_DOWNLOAD_HALFWAY}'
  sleep "${{FAKE_NVM_SECONDS:-0}}"
  echo '{NVM_DOWNLOAD_NOISE}'
  printf '#!/bin/sh\necho v22.0.0\n' > "$NVM_DIR/bin/node"
  printf '#!/bin/sh\necho "{NPM_NOISE[0]}"\necho "{NPM_NOISE[1]}"\nprintf "#!/bin/sh\\n[ \\"\\$1\\" = --help ] && echo \\"  up [options]\\"\\nexit 0\\n" > "$NVM_DIR/bin/gaia"; chmod +x "$NVM_DIR/bin/gaia"\n' > "$NVM_DIR/bin/npm"
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
        f"    printf '#!/bin/sh\\n[ \"$1\" = --help ] && echo \"  up [options]   Install GAIA\"\\nexit 0\\n' > '{bin_dir}/gaia'\n"
        f"    chmod +x '{bin_dir}/gaia'"
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


def test_no_node_yet_installs_it_quietly_in_one_line(fresh_server: dict[str, str]) -> None:
    result = _run(fresh_server)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "No supported package manager" not in result.stdout
    assert "✓ Node.js 22.0.0 installed" in result.stdout
    assert "[info]" not in result.stdout


def test_nvm_install_prints_a_command_that_loads_nvm_then_runs_gaia_up(
    fresh_server: dict[str, str],
) -> None:
    result = _run(fresh_server)

    assert result.returncode == 0, result.stdout + result.stderr
    nvm_dir = Path(fresh_server["HOME"]) / ".nvm"
    assert f'Next, run:  . "{nvm_dir}/nvm.sh" && gaia up' in result.stdout
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


def test_gaia_already_on_path_gets_one_next_step(
    fresh_server: dict[str, str], tmp_path: Path
) -> None:
    bin_dir = Path(fresh_server["PATH"])
    _write_executable(bin_dir / "npm", _fake_npm(tmp_path, _gaia_installer(bin_dir)))

    result = _run(fresh_server)

    assert result.returncode == 0, result.stdout + result.stderr
    assert GET_STARTED_UP in result.stdout
    assert "gaia status" not in result.stdout
    assert "\033[" not in result.stdout  # piped: no colour codes


def test_a_cli_without_up_is_pointed_at_init(fresh_server: dict[str, str], tmp_path: Path) -> None:
    bin_dir = Path(fresh_server["PATH"])
    pre_up_cli = (
        f"    mkdir -p '{bin_dir}'\n"
        f"    printf '#!/bin/sh\\n[ \"$1\" = --help ] && echo \"  init [options]   Full setup\"\\nexit 0\\n' > '{bin_dir}/gaia'\n"
        f"    chmod +x '{bin_dir}/gaia'"
    )
    _write_executable(bin_dir / "npm", _fake_npm(tmp_path, pre_up_cli))

    result = _run(fresh_server)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "gaia init" in result.stdout
    assert "gaia up" not in result.stdout


def test_npm_prefix_off_path_prints_the_path_fix_then_gaia_up(
    fresh_server: dict[str, str], tmp_path: Path
) -> None:
    prefix = tmp_path / "npm-global"
    _write_executable(
        Path(fresh_server["PATH"]) / "npm", _fake_npm(prefix, _gaia_installer(prefix / "bin"))
    )

    result = _run(fresh_server)

    assert result.returncode == 0, result.stdout + result.stderr
    assert f'Next, run:  export PATH="{prefix}/bin:$PATH" && gaia up' in result.stdout
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


SPINNER_FRAME_RE = re.compile("[⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏]")
CLEAR_LINE = "\r\x1b[K"
SHOW_CURSOR = "\x1b[?25h"
SIGINT_EXIT_CODE = 130
PTY_READ_TIMEOUT_SECONDS = 60
POSIX_SHELLS = [path for path in map(shutil.which, ("sh", "dash")) if path]


def _drain(master: int, proc: subprocess.Popen[bytes], interrupt_on: str | None) -> str:
    """Read the pty to EOF; once interrupt_on appears, SIGINT the process group as Ctrl-C does."""
    out = b""
    interrupted = False
    deadline = time.monotonic() + PTY_READ_TIMEOUT_SECONDS
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not select.select([master], [], [], remaining)[0]:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=30)
            pytest.fail(
                f"install.sh still held the pty after {PTY_READ_TIMEOUT_SECONDS}s:\n{out.decode()}"
            )
        try:
            chunk = os.read(master, 4096)
        except OSError:  # EIO: every writer to the pty has exited
            break
        if not chunk:
            break
        out += chunk
        if interrupt_on and not interrupted and interrupt_on.encode() in out:
            os.killpg(proc.pid, signal.SIGINT)
            interrupted = True
    proc.wait(timeout=30)
    return out.decode()


def _run_on_tty(
    shell: str, env: dict[str, str], interrupt_on: str | None = None
) -> tuple[int, str]:
    """Run install.sh with a terminal on stdout, in a new session so it has no /dev/tty to prompt on."""
    master, slave = pty.openpty()
    proc = subprocess.Popen(
        [shell, str(INSTALL_SH)],
        stdin=subprocess.DEVNULL,
        stdout=slave,
        stderr=slave,
        env={**env, "TERM": "xterm-256color"},
        start_new_session=True,
    )
    os.close(slave)
    try:
        output = _drain(master, proc, interrupt_on)
    finally:
        os.close(master)
    return proc.returncode, output


@pytest.mark.parametrize("shell", POSIX_SHELLS)
def test_a_terminal_sees_each_slow_step_live_with_its_progress_and_time(
    fresh_server: dict[str, str], shell: str
) -> None:
    fresh_server["FAKE_NVM_SECONDS"] = "2"

    code, output = _run_on_tty(shell, fresh_server)

    assert code == 0, output
    frames = output.split(CLEAR_LINE)
    downloading = [frame for frame in frames if "Downloading Node.js · 45.0%" in frame]
    assert downloading, output
    assert SPINNER_FRAME_RE.search(downloading[-1])
    assert re.search(r"\x1b\[2m\d+s\x1b\[0m", downloading[-1])  # its ticking timer
    assert any("Downloading the Node.js installer" in frame for frame in frames)
    # The live line is erased and the cursor shown before the ✓ line takes its place.
    assert f"{CLEAR_LINE}{SHOW_CURSOR}  \x1b[0;32m✓\x1b[0m Node.js 22.0.0 installed" in output
    for noise in (NVM_NOISE, NVM_DOWNLOAD_NOISE, *NPM_NOISE):
        assert noise not in output


@pytest.mark.parametrize("shell", POSIX_SHELLS)
def test_ctrl_c_mid_step_leaves_a_clean_line_and_exits_130(
    fresh_server: dict[str, str], tmp_path: Path, shell: str
) -> None:
    _write_executable(Path(fresh_server["PATH"]) / "npm", _fake_npm(tmp_path, "    sleep 30"))
    started = time.monotonic()

    code, output = _run_on_tty(shell, fresh_server, interrupt_on="Installing the GAIA CLI")

    assert code == SIGINT_EXIT_CODE, output
    assert time.monotonic() - started < 20  # the sleeping npm did not outlive the installer
    after_last_clear = output.rsplit(CLEAR_LINE, 1)[1]
    assert after_last_clear.startswith(SHOW_CURSOR)
    assert "Cancelled." in after_last_clear
    assert not SPINNER_FRAME_RE.search(after_last_clear)


def test_piped_output_has_no_spinner_or_carriage_returns(fresh_server: dict[str, str]) -> None:
    fresh_server["FAKE_NVM_SECONDS"] = "2"

    result = _run(fresh_server)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "\r" not in result.stdout
    assert not SPINNER_FRAME_RE.search(result.stdout)
    assert "✓ Node.js 22.0.0 installed" in result.stdout
