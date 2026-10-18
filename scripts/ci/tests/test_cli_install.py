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
import sys
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


def test_a_node_already_here_still_opens_the_step_list(
    fresh_server: dict[str, str], tmp_path: Path
) -> None:
    bin_dir = Path(fresh_server["PATH"])
    _write_executable(bin_dir / "node", "#!/bin/sh\necho v22.11.0\n")
    _write_executable(bin_dir / "npm", _fake_npm(tmp_path, _gaia_installer(bin_dir)))

    result = _run(fresh_server)

    assert result.returncode == 0, result.stdout + result.stderr
    lines = result.stdout.splitlines()
    node_row = next(i for i, line in enumerate(lines) if "Node.js 22.11.0 found" in line)
    assert "GAIA CLI" in lines[node_row + 1]


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


# Real run (0.7.0-beta.4 over SSH): Node came through nvm, so the user's own shell had no gaia.
def test_an_nvm_install_puts_gaia_on_the_shells_own_path(fresh_server: dict[str, str]) -> None:
    bin_dir = Path(fresh_server["PATH"])
    fresh_server["GAIA_BIN_DIR"] = str(bin_dir)

    result = _run(fresh_server)

    assert result.returncode == 0, result.stdout + result.stderr
    assert GET_STARTED_UP in result.stdout
    assert "nvm.sh" not in result.stdout
    launched = subprocess.run(
        [str(bin_dir / "gaia"), "--help"],
        capture_output=True,
        check=False,
        text=True,
        env={"PATH": str(bin_dir)},
    )
    assert launched.returncode == 0, launched.stderr
    assert "up [options]" in launched.stdout


def test_the_launcher_keeps_the_node_gaia_was_installed_with(
    fresh_server: dict[str, str], tmp_path: Path
) -> None:
    bin_dir = Path(fresh_server["PATH"])
    fresh_server["GAIA_BIN_DIR"] = str(bin_dir)
    assert _run(fresh_server).returncode == 0
    nvm_bin = Path(fresh_server["HOME"]) / ".nvm" / "bin"
    _write_executable(nvm_bin / "gaia", "#!/bin/sh\ncommand -v node\n")
    newer_node = tmp_path / "newer-node"
    newer_node.mkdir()
    _write_executable(newer_node / "node", "#!/bin/sh\necho v24.0.0\n")

    launched = subprocess.run(
        [str(bin_dir / "gaia")],
        capture_output=True,
        check=False,
        text=True,
        env={"PATH": f"{newer_node}:{bin_dir}"},
    )

    assert launched.stdout.strip() == str(nvm_bin / "node")


def _pkg_mgr_with_bin_off_path(prefix: Path) -> str:
    """npm, pnpm or bun: reports prefix as its global folder and installs gaia under it."""
    return f"""#!/bin/sh
case "$1 $2" in
  "--version "*) echo 1.0.0 ;;
  "config get") echo '{prefix}' ;;
  "bin -g"|"pm bin") echo '{prefix}/bin' ;;
  *)
    mkdir -p '{prefix}/bin'
    printf '#!/bin/sh\\n[ "$1" = --help ] && echo "  up [options]"\\nexit 0\\n' > '{prefix}/bin/gaia'
    chmod +x '{prefix}/bin/gaia'
    ;;
esac
"""


@pytest.mark.parametrize("pkg_mgr", ["npm", "pnpm", "bun"])
def test_a_global_bin_off_path_gets_a_launcher_for_every_package_manager(
    fresh_server: dict[str, str], tmp_path: Path, pkg_mgr: str
) -> None:
    bin_dir = Path(fresh_server["PATH"])
    prefix = tmp_path / "global"
    _write_executable(bin_dir / pkg_mgr, _pkg_mgr_with_bin_off_path(prefix))
    fresh_server["GAIA_BIN_DIR"] = str(bin_dir)

    result = _run(fresh_server)

    assert result.returncode == 0, result.stdout + result.stderr
    assert GET_STARTED_UP in result.stdout
    assert f"GAIA_CLI='{prefix}/bin/gaia'" in (bin_dir / "gaia").read_text()


def test_a_rerun_points_the_launcher_at_the_new_install(
    fresh_server: dict[str, str], tmp_path: Path
) -> None:
    bin_dir = Path(fresh_server["PATH"])
    _write_executable(
        bin_dir / "gaia",
        '#!/bin/sh\n# Written by the GAIA installer\nexec /gone/gaia "$@"\n',
    )
    prefix = tmp_path / "global"
    _write_executable(bin_dir / "npm", _pkg_mgr_with_bin_off_path(prefix))
    fresh_server["GAIA_BIN_DIR"] = str(bin_dir)

    result = _run(fresh_server)

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"GAIA_CLI='{prefix}/bin/gaia'" in (bin_dir / "gaia").read_text()


def test_a_launcher_folder_off_the_path_falls_back_to_the_load_nvm_step(
    fresh_server: dict[str, str], tmp_path: Path
) -> None:
    fresh_server["GAIA_BIN_DIR"] = str(tmp_path / "not-on-path")

    result = _run(fresh_server)

    assert result.returncode == 0, result.stdout + result.stderr
    assert 'nvm.sh" && gaia up' in result.stdout
    assert not (tmp_path / "not-on-path").exists()


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
    shell: str, env: dict[str, str], interrupt_on: str | None = None, term: str = "xterm-256color"
) -> tuple[int, str]:
    """Run install.sh with a terminal on stdout, in a new session so it has no /dev/tty to prompt on."""
    master, slave = pty.openpty()
    proc = subprocess.Popen(
        [shell, str(INSTALL_SH)],
        stdin=subprocess.DEVNULL,
        stdout=slave,
        stderr=slave,
        env={**env, "TERM": term},
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
    assert re.search(r"\x1b\[2m *\d+s\x1b\[0m", downloading[-1])  # its ticking timer, right-aligned
    assert any("Downloading the Node.js installer" in frame for frame in frames)
    # The live line is erased and the cursor shown before the ✓ line takes its place.
    assert f"{CLEAR_LINE}{SHOW_CURSOR}  \x1b[0;32m✓\x1b[0m Node.js 22.0.0 installed" in output
    for noise in (NVM_NOISE, NVM_DOWNLOAD_NOISE, *NPM_NOISE):
        assert noise not in output


LOGO_GLYPHS = "▀▀▀"
TRUECOLOR_FILL = "\x1b[38;2;15;83;124m"
ANSI256_FILL = "\x1b[38;5;24m"
ANSI16_FILL = "\x1b[34m"


@pytest.mark.parametrize("shell", POSIX_SHELLS)
@pytest.mark.parametrize(
    ("terminal", "fill"),
    [
        ({"COLORTERM": "truecolor"}, TRUECOLOR_FILL),
        # SSH forwards TERM but not COLORTERM; the CLI still paints truecolor there.
        ({}, TRUECOLOR_FILL),
        ({"TERM_PROGRAM": "Apple_Terminal"}, ANSI256_FILL),
        ({"TERM": "xterm"}, ANSI16_FILL),
        ({"NO_COLOR": "1"}, None),
    ],
    ids=["truecolor", "ssh-256color", "256-colour", "16-colour", "no-color"],
)
def test_a_terminal_opens_with_the_logo_beside_the_title(
    fresh_server: dict[str, str], shell: str, terminal: dict[str, str], fill: str | None
) -> None:
    env = {**fresh_server, **{k: v for k, v in terminal.items() if k != "TERM"}}
    code, output = _run_on_tty(shell, env, term=terminal.get("TERM", "xterm-256color"))

    assert code == 0, output
    assert LOGO_GLYPHS in output
    assert "GAIA installer" in output
    assert "latest" in output
    assert (fill in output) if fill else ("\x1b[" not in output.split("GAIA installer")[0])


@pytest.mark.parametrize("shell", POSIX_SHELLS)
def test_a_terminal_too_narrow_for_the_logo_gets_the_one_line_header(
    fresh_server: dict[str, str], shell: str
) -> None:
    code, output = _run_on_tty(shell, {**fresh_server, "COLUMNS": "30"})

    assert code == 0, output
    assert LOGO_GLYPHS not in output
    assert "GAIA installer" in output


def test_piped_output_has_the_one_line_header_only(fresh_server: dict[str, str]) -> None:
    result = _run({**fresh_server, "COLORTERM": "truecolor"})

    assert result.returncode == 0, result.stdout + result.stderr
    assert LOGO_GLYPHS not in result.stdout
    assert "\x1b" not in result.stdout
    assert result.stdout.startswith("\n  GAIA installer\n\n")


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


ERASE_PROMPT = "\x1b[1A\x1b[2K\x1b[1A\x1b[2K\r"

# Makes the pty on stdin the controlling terminal of a new session, so install.sh's /dev/tty is it.
TAKE_PTY_AS_TTY = (
    "import fcntl, os, sys, termios; "
    "fcntl.ioctl(0, termios.TIOCSCTTY, 0); "
    "os.execvp(sys.argv[1], sys.argv[1:])"
)


def _answer_setup_prompt(env: dict[str, str], answer: str) -> str:
    """Run install.sh with a pty as its terminal, and answer "Set up GAIA now?" on it."""
    master, slave = pty.openpty()
    proc = subprocess.Popen(
        [sys.executable, "-c", TAKE_PTY_AS_TTY, "sh", str(INSTALL_SH)],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        env={**env, "TERM": "xterm-256color"},
        start_new_session=True,
    )
    os.close(slave)
    out = b""
    answered = False
    deadline = time.monotonic() + PTY_READ_TIMEOUT_SECONDS
    try:
        while time.monotonic() < deadline:
            if not select.select([master], [], [], 1)[0]:
                if proc.poll() is not None:
                    break
                continue
            try:
                chunk = os.read(master, 4096)
            except OSError:  # EIO: every writer to the pty has exited
                break
            if not chunk:
                break
            out += chunk
            if not answered and b"[Y/n] " in out:
                os.write(master, f"{answer}\n".encode())
                answered = True
    finally:
        os.close(master)
    proc.wait(timeout=30)
    assert answered, out.decode()
    return out.decode()


def _gaia_that_says_it_ran(bin_dir: Path) -> str:
    return (
        f"    mkdir -p '{bin_dir}'\n"
        f'    printf \'#!/bin/sh\\n[ "$1" = --help ] && echo "  up [options]" && exit 0\\necho "gaia $1 ran under the installer header: ${{GAIA_CONTINUES_INSTALLER:-no}}"\\n\' > \'{bin_dir}/gaia\'\n'
        f"    chmod +x '{bin_dir}/gaia'"
    )


def test_a_yes_erases_the_question_before_gaia_up_takes_the_screen(
    fresh_server: dict[str, str], tmp_path: Path
) -> None:
    bin_dir = Path(fresh_server["PATH"])
    _write_executable(bin_dir / "npm", _fake_npm(tmp_path, _gaia_that_says_it_ran(bin_dir)))

    output = _answer_setup_prompt(fresh_server, "y")

    after_question = output.split("[Y/n] ", 1)[1]
    assert ERASE_PROMPT in after_question
    assert after_question.index(ERASE_PROMPT) < after_question.index("gaia up ran")
    # gaia up carries on under the installer's header instead of drawing a second one.
    assert "gaia up ran under the installer header: 1" in after_question
    assert "Next, run:" not in after_question


def test_a_no_keeps_the_question_and_says_what_to_run_later(
    fresh_server: dict[str, str], tmp_path: Path
) -> None:
    bin_dir = Path(fresh_server["PATH"])
    _write_executable(bin_dir / "npm", _fake_npm(tmp_path, _gaia_that_says_it_ran(bin_dir)))

    output = _answer_setup_prompt(fresh_server, "n")

    after_question = output.split("[Y/n] ", 1)[1]
    assert ERASE_PROMPT not in after_question
    assert "gaia up ran" not in after_question
    assert "Next, run:" in after_question
