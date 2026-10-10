"""A stack process dies with the test process that started it, however that process dies.

Each stack process leads its own process group, so killing the test process's
group never reaches it; on a dev box a hard-killed pytest left APIs, hosts and
engines running. Here a throwaway parent starts one stack process through the
stack's own spawn helper, and that process starts a grandchild, as a host starts
its engine. The parent is SIGKILLed: both must be gone.
"""

from __future__ import annotations

from collections.abc import Callable
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

from tests.integration.real.browser._stack.processes import API_ROOT, READY_SECONDS

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="PR_SET_PDEATHSIG is Linux-only"
)

#: A stack process that starts a grandchild, then writes both pids: argv[1] is where.
_CHILD = """
import os, subprocess, sys, time
grandchild = subprocess.Popen(["sleep", "600"])
open(sys.argv[1], "w").write(f"{os.getpid()} {grandchild.pid}")
time.sleep(600)
"""
#: The throwaway parent: starts _CHILD through StackProcess, then waits to be killed.
_PARENT = """
import os, sys, time
from pathlib import Path
from tests.integration.real.browser._stack.processes import StackProcess
pids = Path(sys.argv[1])
StackProcess(
    name="probe",
    argv=[sys.executable, "-c", sys.argv[2], str(pids)],
    env=dict(os.environ),
    log_path=pids.with_suffix(".log"),
).start()
time.sleep(600)
"""
#: How long the kernel gets to end the stack process once its parent is gone.
_DEATH_SECONDS = 20.0


def _alive(pid: int) -> bool:
    """Whether pid runs: a zombie (dead, not yet reaped by whoever inherited it) does not."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except FileNotFoundError:
        return False
    return stat.rsplit(") ", 1)[1].split()[0] != "Z"


def _wait_for(condition: Callable[[], object], what: str, seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.1)
    raise AssertionError(f"{what} within {seconds}s")


def test_a_hard_killed_test_process_takes_its_stack_processes_and_their_engines_along(
    tmp_path: Path,
) -> None:
    pids_file = tmp_path / "pids"
    parent = subprocess.Popen(
        [sys.executable, "-c", _PARENT, str(pids_file), _CHILD],
        cwd=API_ROOT,
        env={**os.environ, "PYTHONPATH": str(API_ROOT)},
    )
    try:
        # The parent cold-imports the app before it starts anything; a parent that dies doing so fails at once.
        _wait_for(
            lambda: (pids_file.exists() and pids_file.read_text()) or parent.poll() is not None,
            "the stack process started",
            READY_SECONDS,
        )
        assert parent.poll() is None, f"the probe parent exited {parent.returncode} before starting"
        child, grandchild = (int(pid) for pid in pids_file.read_text().split())
        assert _alive(child) and _alive(grandchild)

        parent.send_signal(signal.SIGKILL)
        parent.wait()

        _wait_for(
            lambda: not _alive(child) and not _alive(grandchild),
            "the stack process died",
            _DEATH_SECONDS,
        )
    finally:
        if parent.poll() is None:
            parent.kill()
