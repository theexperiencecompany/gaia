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
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from e2b import Template

JUICEFS_VERSION = "1.3.0"
JUICEFS_TARBALL = (
    f"https://github.com/juicedata/juicefs/releases/download/v{JUICEFS_VERSION}/"
    f"juicefs-{JUICEFS_VERSION}-linux-amd64.tar.gz"
)
TEMPLATE_NAME_DEFAULT = "gaia-coder"

MOUNT_SCRIPT_PATH = Path(__file__).parent / "mount_juicefs.sh"


def build(name: str) -> str:
    if not os.environ.get("E2B_API_KEY"):
        raise SystemExit("E2B_API_KEY is not set in the environment")
    if not MOUNT_SCRIPT_PATH.exists():
        raise SystemExit(f"Mount script not found at {MOUNT_SCRIPT_PATH}")

    # All system-level work must run as root: apt_install does (auto), but
    # run_cmd / copy default to the image's user (non-root for python:3.11).
    builder = (
        Template(file_context_path=str(MOUNT_SCRIPT_PATH.parent))
        .from_python_image("3.11")
        .apt_install(
            [
                "fuse3",
                "ca-certificates",
                "postgresql-client",
                "curl",
                "tar",
                "sudo",
            ]
        )
        # Allow non-root user to mount FUSE (juicefs mount needs it)
        .run_cmd(
            "sed -i 's/^#user_allow_other/user_allow_other/' /etc/fuse.conf",
            user="root",
        )
        # Install juicefs binary
        .run_cmd(f"curl -fsSL {JUICEFS_TARBALL} -o /tmp/juicefs.tar.gz", user="root")
        .run_cmd("tar -xzf /tmp/juicefs.tar.gz -C /tmp", user="root")
        .run_cmd("install -m 0755 /tmp/juicefs /usr/local/bin/juicefs", user="root")
        .run_cmd(
            "rm -rf /tmp/juicefs.tar.gz /tmp/juicefs /tmp/LICENSE /tmp/README.md",
            user="root",
        )
        # Cache + workspace dirs, world-writable so the default sandbox user
        # can mount under them. /etc/gaia is created later (after the copy).
        .run_cmd(
            "mkdir -p /var/cache/juicefs /workspace && "
            "chmod 0777 /var/cache/juicefs /workspace",
            user="root",
        )
        # Stage the mount script in /tmp (E2B's copy step has issues writing
        # directly into /etc/...), then move it into place as root. The
        # source path is interpreted relative to file_context_path on the
        # builder constructor above.
        .copy("mount_juicefs.sh", "/tmp/mount.sh", mode=0o755)
        .run_cmd(
            "mkdir -p /etc/gaia && "
            "mv /tmp/mount.sh /etc/gaia/mount.sh && "
            "chown root:root /etc/gaia/mount.sh && "
            "chmod 0755 /etc/gaia/mount.sh /etc/gaia",
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
