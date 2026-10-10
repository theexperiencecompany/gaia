"""Run one stack process so it dies with the test process that started it, engines and all.

Run as python -m tests.integration.real.browser._stack.guard <parent pid> <argv...>.
The guard leads its own process group (the stack starts it in a new session),
asks the kernel to signal it when its parent dies (PR_SET_PDEATHSIG, Linux), and
runs argv as its child in the same group. When the test process is killed hard,
the signal arrives and the guard SIGKILLs the whole group: the child and every
engine the child started. A normal stop's SIGTERM reaches the child itself, and
the guard waits for it and exits with its code.
"""

from __future__ import annotations

import ctypes
import os
import signal
import subprocess  # nosec B404 -- runs the stack's own fixed argv, never a shell
import sys
from types import FrameType

#: prctl's option for the signal a process receives when its parent dies.
_PR_SET_PDEATHSIG = 1
#: The parent-death signal: not SIGTERM, which a normal stop sends to the whole group.
_PARENT_DIED = signal.SIGUSR1


def _kill_the_group(_signum: int, _frame: FrameType | None) -> None:
    os.killpg(0, signal.SIGKILL)


def _die_with(parent_pid: int) -> None:
    """Have the kernel signal this process when its parent dies; a parent already gone kills the group now."""
    if not sys.platform.startswith("linux"):
        raise RuntimeError(
            "the browser stack ties its processes to the test process with prctl, Linux only"
        )
    signal.signal(_PARENT_DIED, _kill_the_group)
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(_PR_SET_PDEATHSIG, _PARENT_DIED, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "prctl(PR_SET_PDEATHSIG) failed")
    # The parent may have died before prctl took effect; then nothing will ever signal.
    if os.getppid() != parent_pid:
        _kill_the_group(_PARENT_DIED, None)


def main() -> None:
    parent_pid, argv = int(sys.argv[1]), sys.argv[2:]
    _die_with(parent_pid)
    child = subprocess.Popen(argv)  # nosec B603 -- the stack's fixed argv
    # Ignored only after the spawn, which would inherit it: a stop's SIGTERM is the
    # child's to act on, and the guard outlives it to report the child's exit.
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    sys.exit(child.wait())


if __name__ == "__main__":
    main()
