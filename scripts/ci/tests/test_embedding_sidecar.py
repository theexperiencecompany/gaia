"""embedding-sidecar.sh: who owns the port.

``start`` used to decide the port was free from the pidfile alone. A pidfile
can be lost — a cleaned RUNDIR, a killed job, a reboot that cleared /tmp but
not the process — while a live uvicorn keeps listening, and every later job on
that runner index then died with "address already in use" (seen on gaia-ci for
port 28900).

These bind a REAL socket on a real high port and let the script find it with
the real ``ss``/``lsof``: bash's ``kill`` is a builtin, so a stubbed kill
proves nothing about whether the holder actually goes away. Only ``uv`` is
stubbed, so no model is ever loaded.
"""

from __future__ import annotations

import os
from pathlib import Path
import socket
import subprocess
import time

import pytest

CI = Path(__file__).parent.parent
SCRIPT = CI / "embedding-sidecar.sh"

# Ports >= 30000 only: the box's services and the per-job containers live below
# that, and nothing here may collide with a real lane.
PORT_BASE = 39000
RUNNER_INDEX = "0"

UV_STUB = """\
#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$REC/uv.log"
exit 1
"""

# argv is what the script matches on, so the holder's identity lives in the
# path it is launched from.
LISTENER_SRC = """\
import socket, sys, time
s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("127.0.0.1", int(sys.argv[1])))
s.listen(8)
sys.stderr.write("listening\\n")
sys.stderr.flush()
time.sleep(300)
"""


def free_port() -> int:
    """A port in our own range that nothing currently holds."""
    for port in range(PORT_BASE, PORT_BASE + 400, 10):
        with socket.socket() as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
            except OSError:
                continue
        return port
    raise RuntimeError("no free port in the test range")


@pytest.fixture
def port() -> int:
    return free_port()


def make_env(tmp_path: Path, port: int, **extra: str) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    uv = bin_dir / "uv"
    uv.write_text(UV_STUB)
    uv.chmod(0o755)
    env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "HOME": os.environ.get("HOME", "/tmp"),
        "REC": str(tmp_path),
        "GAIA_CI_RUNDIR": str(tmp_path),
        "RUNNER_INDEX": RUNNER_INDEX,
        "SIDECAR_PORT_BASE": str(port),
    }
    env.update(extra)
    return env


def run(tmp_path: Path, port: int, *args: str, **extra: str):
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        env=make_env(tmp_path, port, **extra),
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
        cwd=CI.parent.parent,
    )


def start_listener(tmp_path: Path, port: int, *, ours: bool) -> subprocess.Popen:
    """Hold `port` with a process whose argv does (or does not) look like ours."""
    name = "app_services_embedding_sidecar_server.py" if ours else "some_other_daemon.py"
    src = tmp_path / name
    src.write_text(LISTENER_SRC)
    proc = subprocess.Popen(
        ["python3", str(src), str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert proc.stderr is not None
    assert proc.stderr.readline().strip() == "listening", "listener failed to bind"
    return proc


def still_alive(proc: subprocess.Popen) -> bool:
    for _ in range(30):
        if proc.poll() is not None:
            return False
        time.sleep(0.1)
    return proc.poll() is None


def cleanup(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        proc.kill()
    proc.wait(timeout=10)


def test_orphaned_sidecar_on_the_port_is_killed(tmp_path: Path, port: int) -> None:
    # The pidfile is gone but our own sidecar is still listening: reclaim it.
    holder = start_listener(tmp_path, port, ours=True)
    try:
        proc = run(tmp_path, port, "start")
        assert f"port {port} is held by an orphaned embedding sidecar" in proc.stderr
        assert not still_alive(holder), "the orphaned sidecar was left holding the port"
        # Having reclaimed the port, it goes on to launch.
        assert (tmp_path / "uv.log").exists()
    finally:
        cleanup(holder)


def test_a_foreign_listener_fails_loud_and_names_the_holder(tmp_path: Path, port: int) -> None:
    # Something that is NOT ours must never be killed — and must not be
    # silently started over either.
    holder = start_listener(tmp_path, port, ours=False)
    try:
        proc = run(tmp_path, port, "start")
        assert proc.returncode == 1
        assert "::error::" in proc.stderr
        assert f"port {port} is held by pid {holder.pid}" in proc.stderr
        assert "some_other_daemon.py" in proc.stderr
        assert "Refusing to start" in proc.stderr
        assert holder.poll() is None, "a foreign listener was killed"
        assert not (tmp_path / "uv.log").exists(), "it started anyway"
    finally:
        cleanup(holder)


def test_a_free_port_is_not_second_guessed(tmp_path: Path, port: int) -> None:
    # Nothing listening: the script proceeds to launch. The uv stub exits at
    # once, so it reports the startup failure — proof it got past the port
    # check rather than refusing on a phantom holder.
    proc = run(tmp_path, port, "start", GAIA_SIDECAR_LOG=str(tmp_path / "s.log"))
    assert "held by" not in proc.stderr
    assert "could not be identified" not in proc.stderr
    assert (tmp_path / "uv.log").exists()
    assert "exited during startup" in proc.stderr


def test_stop_reclaims_a_port_whose_pidfile_was_lost(tmp_path: Path, port: int) -> None:
    holder = start_listener(tmp_path, port, ours=True)
    try:
        proc = run(tmp_path, port, "stop")
        assert proc.returncode == 0
        assert "still held by an orphaned sidecar" in proc.stderr
        assert not still_alive(holder)
    finally:
        cleanup(holder)


def test_stop_leaves_a_foreign_listener_alone(tmp_path: Path, port: int) -> None:
    holder = start_listener(tmp_path, port, ours=False)
    try:
        proc = run(tmp_path, port, "stop")
        assert proc.returncode == 0
        assert holder.poll() is None
    finally:
        cleanup(holder)


def test_stop_never_fails_the_caller(tmp_path: Path, port: int) -> None:
    # Teardown runs from `if: always()`; nothing here may red a green lane.
    proc = run(tmp_path, port, "stop")
    assert proc.returncode == 0


def test_keep_warm_on_the_box_does_not_kill(tmp_path: Path, port: int) -> None:
    holder = start_listener(tmp_path, port, ours=True)
    try:
        (tmp_path / f"gaia-embedding-sidecar-{RUNNER_INDEX}.pid").write_text(f"{holder.pid}\n")
        proc = run(tmp_path, port, "stop", RUNNER_ENVIRONMENT="self-hosted")
        assert proc.returncode == 0
        assert "left warm" in proc.stdout
        assert holder.poll() is None, "keep-warm killed the sidecar"
    finally:
        cleanup(holder)


def test_stop_sidecar_env_defeats_keep_warm(tmp_path: Path, port: int) -> None:
    holder = start_listener(tmp_path, port, ours=True)
    try:
        (tmp_path / f"gaia-embedding-sidecar-{RUNNER_INDEX}.pid").write_text(f"{holder.pid}\n")
        proc = run(tmp_path, port, "stop", RUNNER_ENVIRONMENT="self-hosted", STOP_SIDECAR="1")
        assert proc.returncode == 0
        assert "left warm" not in proc.stdout
        assert not still_alive(holder)
    finally:
        cleanup(holder)


def test_unknown_subcommand_is_usage_and_exit_2(tmp_path: Path, port: int) -> None:
    proc = run(tmp_path, port, "restart")
    assert proc.returncode == 2
    assert "Usage: embedding-sidecar.sh" in proc.stderr
