#!/bin/bash
# Mount JuiceFS at /mnt/jfs and bind-mount the user's prefix to /workspace.
#
# Bundled into the `gaia-coder` E2B template at /etc/gaia/mount.sh and invoked
# by the API after every sandbox cold-start or resume. Idempotent — re-running
# is a no-op when /workspace is already healthy.
#
# Best-effort: if JuiceFS metadata is unreachable (e.g. local-only Postgres in
# dev) or R2 creds are missing, the script falls back to a plain `/workspace`
# directory inside the sandbox's ephemeral filesystem. The agent's bash/read/
# write/edit tools still work; only persistence across sandbox recreates is
# lost. The script always exits 0 unless something catastrophic happens.
#
# Required env (set by app.services.sandbox.lifecycle._create_fresh_sandbox):
#   USER_ID         - GAIA user id; becomes the bind-mount root
# Optional:
#   JFS_META_URL    - PostgreSQL metadata URL. If unset or unreachable, mount
#                     is skipped and /workspace falls back to ephemeral.
#   JFS_R2_KEY      - R2 access key id (forwarded to juicefs)
#   JFS_R2_SECRET   - R2 secret access key

set -uo pipefail

JFS_MOUNT=/mnt/jfs
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

mount_juicefs() {
    if mountpoint -q "$JFS_MOUNT"; then
        return 0
    fi
    sudo mkdir -p "$JFS_MOUNT" /var/cache/juicefs
    # --backup-meta=0  : R2 ListObjects is unsorted; auto-backup would fail.
    # no --writeback   : writeback loses data on sandbox kill — keep durable.
    sudo -E juicefs mount \
        --backup-meta=0 \
        --cache-dir=/var/cache/juicefs \
        --cache-size=8192 \
        --max-uploads=20 \
        --buffer-size=600 \
        --background \
        "$JFS_META_URL" "$JFS_MOUNT" 2>&1
}

if ! mount_juicefs; then
    echo "WARN: juicefs mount failed (metadata DB or R2 unreachable) — " \
         "falling back to ephemeral /workspace" >&2
    ensure_workspace_writable
    exit 0
fi

# JuiceFS mounted — bind-mount user's prefix at /workspace.
sudo mkdir -p "$JFS_MOUNT/users/$USER_ID" "$JFS_MOUNT/skills/$USER_ID"
sudo mkdir -p "$WORKSPACE"
if ! sudo mount --bind "$JFS_MOUNT/users/$USER_ID" "$WORKSPACE"; then
    echo "WARN: bind-mount $JFS_MOUNT/users/$USER_ID → $WORKSPACE failed — " \
         "falling back to ephemeral /workspace" >&2
    ensure_workspace_writable
    exit 0
fi
sudo mkdir -p "$WORKSPACE/skills"
sudo mount --bind "$JFS_MOUNT/skills/$USER_ID" "$WORKSPACE/skills" -o ro || true
sudo chown -R "$(id -u):$(id -g)" "$WORKSPACE" 2>/dev/null || true
mkdir -p "$WORKSPACE/.gaia/runs"
echo "OK: JuiceFS mounted; /workspace is durable" >&2
