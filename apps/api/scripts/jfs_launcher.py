#!/usr/bin/env python3
"""Launch ``juicefs`` with ``PR_SET_DUMPABLE=0`` so its ``/proc/<pid>/*``
entries are inaccessible to non-owner non-``CAP_SYS_PTRACE`` readers.

Background
----------
The juicefs daemon holds the meta-DB URL, ``META_PASSWORD``, and R2 keys in
its process environ. The default kernel rule for ``/proc/<pid>/{environ,
cmdline}`` reads is "owner uid or ``CAP_SYS_PTRACE``"; for a root-owned
process this means an unprivileged sibling user is denied — but a process
that obtained ``CAP_SYS_PTRACE`` (e.g. via ``sudo cat``) is not.

``PR_SET_DUMPABLE(0)`` makes the kernel additionally:
  * Set ``/proc/<pid>/*`` ownership to ``root:root`` mode ``0``.
  * Require ``PTRACE_MODE_READ_FSCREDS`` for any non-owner reader (so a
    ``CAP_SYS_PTRACE`` reader still passes; an unprivileged reader does not).
  * Refuse ``ptrace`` attach from anything that isn't the owner or
    capability-holder.

In the gaia-coder template the unprivileged sandbox user has **no** ``sudo``
(see ``build_e2b_template.py``), so they cannot obtain ``CAP_SYS_PTRACE``.
With ``dumpable=0`` set here, every path from a user shell to the daemon's
secrets is closed — including future regressions where someone accidentally
re-grants sudo, because the dumpable flag is independent of the sudo policy.

The flag survives ``execve(2)`` for non-suid binaries (which juicefs is),
and is inherited across ``fork(2)`` — so when juicefs daemonizes via
``--background`` the child keeps the flag.

Usage
-----
Invoked from ``mount_juicefs.sh`` in place of a bare ``juicefs`` call:

    /etc/gaia/jfs_launcher.py mount --subdir /users/$USER_ID ... $META_URL /mnt/jfs

Mirrors a standard juicefs CLI; everything after ``argv[0]`` is forwarded
unmodified to the juicefs binary.
"""

from __future__ import annotations

import ctypes
import os
import sys

# From <sys/prctl.h>. Hard-coded because the kernel ABI is stable and pulling
# in a Python wrapper for one constant would add an apt/pip dependency to a
# script that has to run in the minimal sandbox image.
PR_SET_DUMPABLE = 4

JUICEFS_BIN = "juicefs"


def _set_non_dumpable() -> None:
    """Flip the calling process's dumpable flag to 0.

    Exits the process on failure — there is no safe fallback. If we cannot
    set the flag the daemon would launch with default visibility, which is
    the exact security regression this launcher exists to prevent.
    """
    libc = ctypes.CDLL("libc.so.6", use_errno=True)
    rc = libc.prctl(PR_SET_DUMPABLE, 0, 0, 0, 0)
    if rc != 0:
        err = ctypes.get_errno()
        print(
            f"jfs_launcher: prctl(PR_SET_DUMPABLE, 0) failed: errno={err}",
            file=sys.stderr,
        )
        sys.exit(1)


def main() -> None:
    _set_non_dumpable()
    # ``execvp`` replaces the current process image with juicefs. The
    # dumpable flag persists across this exec because juicefs is not
    # set-uid (see prctl(2) PR_SET_DUMPABLE notes).
    os.execvp(JUICEFS_BIN, [JUICEFS_BIN, *sys.argv[1:]])


if __name__ == "__main__":
    main()
