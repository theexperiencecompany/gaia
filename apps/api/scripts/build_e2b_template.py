#!/usr/bin/env python3
"""Build (or rebuild) the `gaia-coder` E2B template.

Bakes `fuse3`, `juicefs`, and the mount script into a custom Python sandbox so
cold-start cost is dominated by E2B's microVM boot, not package install. Each
build produces a versioned template; the alias `gaia-coder` always points at
the latest.

Usage:
    cd apps/api
    uv run python scripts/build_e2b_template.py [--name gaia-coder]

Requires `E2B_API_KEY` in the env. Prints the resulting template ID — set it
as `E2B_TEMPLATE_ID` in Infisical (and the gaia-backend container will pick
it up on next boot).

Security posture
----------------
The default E2B Python image ships its sandbox user as a member of `sudo` with
NOPASSWD ALL — convenient for ad-hoc package installs, but catastrophic for
multi-tenant isolation: the JuiceFS daemon runs as root and (regardless of how
carefully we deliver creds) holds the meta-DB password somewhere in its
process tree. With unrestricted sudo, a malicious agent could `sudo cat
/proc/<juicefs_pid>/environ` and recover those creds — then re-mount the
cross-user namespace without `--subdir`. The fix is to remove the sandbox user
from the `sudo` group entirely.

The API drives root-needing operations (running mount.sh, tailing the JuiceFS
access log) via `sbx.commands.run(..., user="root")`, which e2b's envd honors
directly — no sudo involved. The agent's bash tool runs commands as the
unprivileged sandbox user; it has no path to root.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

from e2b import Template

JUICEFS_VERSION = "1.3.0"
JUICEFS_TARBALL = (
    f"https://github.com/juicedata/juicefs/releases/download/v{JUICEFS_VERSION}/"
    f"juicefs-{JUICEFS_VERSION}-linux-amd64.tar.gz"
)
TEMPLATE_NAME_DEFAULT = "gaia-coder"

MOUNT_SCRIPT_PATH = Path(__file__).parent / "mount_juicefs.sh"
JFS_LAUNCHER_PATH = Path(__file__).parent / "jfs_launcher.py"


def build(name: str) -> str:
    if not os.environ.get("E2B_API_KEY"):
        raise SystemExit("E2B_API_KEY is not set in the environment")
    if not MOUNT_SCRIPT_PATH.exists():
        raise SystemExit(f"Mount script not found at {MOUNT_SCRIPT_PATH}")
    if not JFS_LAUNCHER_PATH.exists():
        raise SystemExit(f"jfs_launcher not found at {JFS_LAUNCHER_PATH}")

    # All system-level work must run as root: apt_install does (auto), but
    # run_cmd / copy default to the image's user (non-root for python:3.11).
    builder = (
        Template(file_context_path=str(MOUNT_SCRIPT_PATH.parent))
        .from_python_image("3.11")
        .apt_install(
            [
                # Mount + storage primitives (required for JuiceFS to boot).
                "fuse3",
                "ca-certificates",
                "postgresql-client",
                "curl",
                "tar",
                # Pre-baked because the sandbox user has no `sudo` (see the
                # group-strip below) and cannot install Debian packages
                # at runtime. This list covers ~95% of what coding agents
                # reach for; for anything else, language-level installers
                # (pip --user, npm, cargo, gem --user-install) still work
                # without root. Add packages here when telemetry shows
                # genuine demand rather than letting the agent compile
                # from source in a tight loop.
                "git",
                "jq",
                "ripgrep",
                "fd-find",
                "build-essential",
                "pkg-config",
                "libpq-dev",
                "libssl-dev",
                "libffi-dev",
                "sqlite3",
                "tree",
                "less",
                "vim-tiny",
                "ffmpeg",
                "imagemagick",
                "graphviz",
            ]
        )
        # `user_allow_other` is NOT set in /etc/fuse.conf — leaving it disabled
        # closes a sudo-independent re-mount path. The API always invokes
        # `juicefs mount` as root (via commands.run(user="root")), so the
        # FUSE-as-non-root capability is not needed.
        # Install juicefs binary
        .run_cmd(f"curl -fsSL {JUICEFS_TARBALL} -o /tmp/juicefs.tar.gz", user="root")
        .run_cmd("tar -xzf /tmp/juicefs.tar.gz -C /tmp", user="root")
        .run_cmd("install -m 0755 /tmp/juicefs /usr/local/bin/juicefs", user="root")
        .run_cmd(
            "rm -rf /tmp/juicefs.tar.gz /tmp/juicefs /tmp/LICENSE /tmp/README.md",
            user="root",
        )
        # Strip the sandbox user from every privilege group, then purge the
        # `sudo` package itself. Removing the setuid binary closes the last
        # theoretical escalation surface — even if a future regression added
        # a password or a NOPASSWD rule back, there's no `sudo` for it to
        # apply to. The API uses commands.run(user="root") for the handful
        # of operations that genuinely need root; nothing in our sandbox
        # codepath ever shells out to `sudo`.
        .run_cmd(
            "set -e; "
            "if id -u user >/dev/null 2>&1; then "
            "  gpasswd -d user sudo 2>/dev/null || true; "
            "  gpasswd -d user wheel 2>/dev/null || true; "
            "fi; "
            "rm -f /etc/sudoers.d/*-user /etc/sudoers.d/90-cloud-init-users "
            "       /etc/sudoers.d/nopasswd-user /etc/sudoers.d/user; "
            "if [ -f /etc/sudoers ]; then "
            "  sed -i '/^%sudo[[:space:]].*NOPASSWD/d' /etc/sudoers; "
            "  sed -i '/^user[[:space:]].*NOPASSWD/d' /etc/sudoers; "
            "fi; "
            # Purge sudo entirely. `--allow-remove-essential` is not needed
            # — sudo is not Essential. Run after the group-strip so we don't
            # leave a sudoers.d entry pointing at a now-removed binary.
            "DEBIAN_FRONTEND=noninteractive apt-get purge -y sudo 2>&1 | tail -3; "
            "apt-get autoremove -y --purge 2>&1 | tail -3; "
            "rm -rf /var/lib/apt/lists/*",
            user="root",
        )
        # Cache + workspace dirs. /workspace and /mnt/jfs are mode 0750 owned
        # by `user` so unprivileged ops work but no cross-uid leak is possible.
        .run_cmd(
            "mkdir -p /var/cache/juicefs /workspace /mnt/jfs && "
            "chown -R user:user /workspace /mnt/jfs && "
            "chmod 0750 /workspace /mnt/jfs && "
            "chmod 0755 /var/cache/juicefs",
            user="root",
        )
        # Stage the mount script in /tmp (E2B's copy step has issues writing
        # directly into /etc/...), then move it into place as root. /etc/gaia
        # is root-owned 0755; mount.sh is root-owned 0750 so only root (via
        # commands.run(user="root")) can execute it.
        # Stage the mount script in /tmp (E2B's copy step has issues writing
        # directly into /etc/...), then move it into place as root. /etc/gaia
        # is root-owned 0755; mount.sh is root-owned 0750 so only root (via
        # commands.run(user="root")) can execute it.
        #
        # `verify_sandbox_hardening.sh` is intentionally NOT baked in — it
        # ships as a push-on-demand diagnostic (upload via sbx.files.write,
        # run, delete) so the sandbox surface stays minimal. The source
        # script lives at apps/api/scripts/verify_sandbox_hardening.sh.
        .copy("mount_juicefs.sh", "/tmp/mount.sh", mode=0o755)
        .copy("jfs_launcher.py", "/tmp/jfs_launcher.py", mode=0o755)
        .run_cmd(
            "mkdir -p /etc/gaia && "
            "mv /tmp/mount.sh /etc/gaia/mount.sh && "
            "mv /tmp/jfs_launcher.py /etc/gaia/jfs_launcher.py && "
            "chown root:root /etc/gaia /etc/gaia/mount.sh "
            "   /etc/gaia/jfs_launcher.py && "
            "chmod 0755 /etc/gaia && "
            "chmod 0750 /etc/gaia/mount.sh && "
            # jfs_launcher.py is 0755 so root-owned juicefs invocations from
            # mount.sh can exec it. It's not a setuid binary; running it as
            # the unprivileged user just runs juicefs as that user (and the
            # daemon would fail to mount without root anyway).
            "chmod 0755 /etc/gaia/jfs_launcher.py",
            user="root",
        )
        # /proc with hidepid=invisible hides PIDs of processes the calling
        # user doesn't own. Combined with the sudo strip above, the sandbox
        # user cannot enumerate (`pgrep`, `ls /proc/`) or read the juicefs
        # daemon's /proc entries. Persist via /etc/fstab so the option
        # re-applies on every sandbox boot, and live-remount so the running
        # build's /proc reflects it too.
        .run_cmd(
            "set -e; "
            "grep -qE '^proc[[:space:]]+/proc' /etc/fstab 2>/dev/null && "
            "  sed -i -E 's|^(proc[[:space:]]+/proc[[:space:]]+proc[[:space:]]+)([^[:space:]]+)|\\1\\2,hidepid=invisible|' /etc/fstab || "
            "  echo 'proc /proc proc defaults,hidepid=invisible 0 0' >> /etc/fstab; "
            "mount -o remount,hidepid=invisible /proc 2>/dev/null || true",
            user="root",
        )
    )

    print(f"Building E2B template '{name}'...", file=sys.stderr)

    def _on_log(entry: object) -> None:
        # E2B streams build logs; surface them so the user can see progress
        print(f"  [e2b build] {entry}", file=sys.stderr)

    info = Template.build(builder, alias=name, on_build_logs=_on_log)
    template_id = (
        getattr(info, "template_id", None)
        or getattr(info, "id", None)
        or getattr(info, "templateID", None)
    )
    if not template_id:
        raise SystemExit(f"Build did not return a template id (got: {info!r})")
    print(template_id)
    return template_id


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--name",
        default=TEMPLATE_NAME_DEFAULT,
        help="Template alias (default: gaia-coder)",
    )
    args = parser.parse_args()
    build(args.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
