#!/usr/bin/env python3
"""Launch juicefs with PR_SET_DUMPABLE=0 so its /proc/<pid>/* is inaccessible to non-owner readers.

The juicefs daemon holds the meta-DB URL, META_PASSWORD, and R2 keys in its
environ. The default kernel rule ("owner uid or CAP_SYS_PTRACE") denies an
unprivileged sibling but not one that obtained CAP_SYS_PTRACE (e.g. via sudo
cat). PR_SET_DUMPABLE(0) additionally sets /proc/<pid>/* to root:root mode 0,
requires PTRACE_MODE_READ_FSCREDS for any non-owner reader, and refuses
ptrace attach from anyone but the owner or capability-holder.

The sandbox user has no sudo (build_e2b_template.py), so this closes every
path to the daemon's secrets independent of the sudo policy — including a
future regression that re-grants it. The flag survives execve (juicefs is
non-suid) and fork, so a --background daemonized child keeps it too, and
mount_juicefs.sh invokes this in place of a bare juicefs call, mirroring the
CLI and forwarding argv[1:] unmodified.
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
