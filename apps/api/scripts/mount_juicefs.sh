#!/bin/bash
# Mount JuiceFS inside the sandbox, exposing ONLY this user's subtree.
#
# Bundled into the `gaia-coder` E2B template at /etc/gaia/mount.sh and invoked
# by the API after every sandbox cold-start or resume. Idempotent — re-running
# is a no-op when /workspace is already healthy.
#
# Isolation model
# ---------------
# JuiceFS shares a single metadata DB and R2 bucket across every user. A naive
# `juicefs mount $META_URL /mnt/jfs` exposes the WHOLE filesystem at /mnt/jfs,
# including every other user's prefix — a trivial cross-user data leak the
# moment the sandbox user runs `ls /mnt/jfs/users/`. We avoid that with two
# defenses:
#
#   1. `--subdir /users/$USER_ID` on the primary mount. JuiceFS scopes the
#      kernel-visible tree to that subdirectory; no parent navigation is
#      possible inside the sandbox. A second `--subdir /skills/$USER_ID`
#      mount serves the read-only skills bind (same JuiceFS instance, but
#      isolated to the user's installed-skills subtree).
#   2. Credentials (`JFS_META_URL`, R2 keys) are passed **per-call** by the
#      API to this script via the `commands.run(envs=...)` parameter — they
#      are NOT in the sandbox-wide envd config. After mount.sh returns, no
#      user-initiated shell can read them out of /proc/self/environ.
#
# Best-effort: if JuiceFS metadata is unreachable (e.g. local-only Postgres in
# dev) or R2 creds are missing, the script falls back to a plain `/workspace`
# directory inside the sandbox's ephemeral filesystem. The agent's bash/read/
# write/edit tools still work; only persistence across sandbox recreates is
# lost. The script always exits 0 unless something catastrophic happens.
#
# Required env (set by app.services.sandbox.lifecycle._mount_env per-call):
#   USER_ID         - GAIA user id; determines the JuiceFS subdir to expose.
# Optional:
#   JFS_META_URL    - PostgreSQL metadata URL. If unset or unreachable, mount
#                     is skipped and /workspace falls back to ephemeral.
#   JFS_R2_KEY      - R2 access key id (forwarded to juicefs)
#   JFS_R2_SECRET   - R2 secret access key

set -uo pipefail

JFS_MOUNT=/mnt/jfs            # primary mount: scoped to /users/$USER_ID
JFS_SKILLS_MOUNT=/mnt/jfs-skills  # secondary mount: scoped to /skills/$USER_ID, ro
WORKSPACE=/workspace

ensure_workspace_writable() {
    sudo mkdir -p "$WORKSPACE" "$WORKSPACE/.gaia/runs"
    sudo chmod 0777 "$WORKSPACE" "$WORKSPACE/.gaia" "$WORKSPACE/.gaia/runs" 2>/dev/null || true
}

# Fast path — /workspace is already a real mount, nothing to do.
if mountpoint -q "$WORKSPACE"; then
    ensure_workspace_writable
    exit 0
fi

if [[ -z "${USER_ID:-}" ]]; then
    echo "WARN: USER_ID not set — falling back to ephemeral /workspace" >&2
    ensure_workspace_writable
    exit 0
fi

if [[ -z "${JFS_META_URL:-}" ]]; then
    echo "WARN: JFS_META_URL not set — falling back to ephemeral /workspace" >&2
    ensure_workspace_writable
    exit 0
fi

export AWS_ACCESS_KEY_ID="${JFS_R2_KEY:-}"
export AWS_SECRET_ACCESS_KEY="${JFS_R2_SECRET:-}"

mount_user_subdir() {
    if mountpoint -q "$JFS_MOUNT"; then
        return 0
    fi
    sudo mkdir -p "$JFS_MOUNT" /var/cache/juicefs
    # --subdir scopes the kernel-visible tree to the user's prefix — every
    # path under $JFS_MOUNT inside the sandbox is rooted at /users/$USER_ID,
    # and there is no way to navigate up to a sibling user. The juicefs
    # daemon itself still talks to the full meta DB (it has to — it owns the
    # locks/permissions/etc.), but the FUSE filesystem it exposes is the
    # subtree.
    # --backup-meta=0 : R2 ListObjects is unsorted; auto-backup would fail.
    # no --writeback  : writeback loses data on sandbox kill — keep durable.
    sudo -E juicefs mount \
        --subdir "/users/$USER_ID" \
        --backup-meta=0 \
        --cache-dir=/var/cache/juicefs \
        --cache-size=8192 \
        --max-uploads=20 \
        --buffer-size=600 \
        --background \
        "$JFS_META_URL" "$JFS_MOUNT" 2>&1
}

mount_skills_subdir() {
    if mountpoint -q "$JFS_SKILLS_MOUNT"; then
        return 0
    fi
    sudo mkdir -p "$JFS_SKILLS_MOUNT"
    # Read-only mount of /skills/$USER_ID — backs /workspace/skills. Same
    # isolation principle: the sandbox sees only this user's installed
    # skills subtree, never the cross-user /skills root.
    sudo -E juicefs mount \
        --subdir "/skills/$USER_ID" \
        --read-only \
        --backup-meta=0 \
        --cache-dir=/var/cache/juicefs \
        --cache-size=1024 \
        --buffer-size=300 \
        --background \
        "$JFS_META_URL" "$JFS_SKILLS_MOUNT" 2>&1
}

# The per-user subtree ``/users/$USER_ID`` and the per-user skills subtree
# ``/skills/$USER_ID`` are pre-created on the HOST side before any sandbox
# command runs — see ``ensure_user_workspace`` and ``ensure_user_skills_dir``
# in apps/api/app/services/storage/juicefs.py, plus the bootstrap call in
# acquire_sandbox below. That keeps the brief "full FS visible" window out
# of the sandbox entirely; we never need an unrestricted mount in here.

if ! mount_user_subdir; then
    echo "WARN: juicefs user --subdir mount failed (metadata DB or R2 " \
         "unreachable) — falling back to ephemeral /workspace" >&2
    ensure_workspace_writable
    exit 0
fi

# JuiceFS user-subdir mounted at $JFS_MOUNT. Bind-mount it at /workspace so
# downstream paths keep working unchanged.
sudo chmod 0777 "$JFS_MOUNT" 2>/dev/null || true
sudo mkdir -p "$WORKSPACE"
if ! sudo mount --bind "$JFS_MOUNT" "$WORKSPACE"; then
    echo "WARN: bind-mount $JFS_MOUNT → $WORKSPACE failed — " \
         "falling back to ephemeral /workspace" >&2
    ensure_workspace_writable
    exit 0
fi
sudo chmod 0777 "$WORKSPACE" 2>/dev/null || true

# Optional skills overlay — best-effort. If /skills/$USER_ID doesn't exist or
# the second mount fails, /workspace/skills falls back to the user's own
# materialized executor-skills subdir under /workspace/skills/.
sudo mkdir -p "$WORKSPACE/skills"
if mount_skills_subdir; then
    sudo mount --bind "$JFS_SKILLS_MOUNT" "$WORKSPACE/skills" -o ro || true
fi

mkdir -p "$WORKSPACE/.gaia/runs" 2>/dev/null || sudo mkdir -p "$WORKSPACE/.gaia/runs"
sudo chmod -R 0777 "$WORKSPACE/.gaia" 2>/dev/null || true
# User-scoped, cross-session dirs (sessions/ are created on demand by the API).
sudo mkdir -p "$WORKSPACE/pinned" "$WORKSPACE/settings"
sudo chmod 0777 "$WORKSPACE/pinned" "$WORKSPACE/settings" 2>/dev/null || true
echo "OK: JuiceFS mounted (subdir-scoped); /workspace is durable" >&2
