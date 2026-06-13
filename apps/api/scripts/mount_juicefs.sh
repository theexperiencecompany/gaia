#!/bin/bash
# Mount JuiceFS inside the sandbox, exposing ONLY this user's subtree.
#
# Bundled into the `gaia-coder` E2B template at /etc/gaia/mount.sh and invoked
# by the API after every sandbox cold-start or resume. Idempotent — re-running
# is a no-op when /workspace is already healthy.
#
# Privilege model
# ---------------
# This script runs AS ROOT. The API invokes it via
# `commands.run(user="root", envs=mount_env)` (see lifecycle._run_mount_script),
# so envd in the sandbox forks the process directly as root and the credentials
# never appear in the unprivileged sandbox user's environ. The sandbox user has
# NO `sudo` capability (the template removes them from the `sudo` group), so a
# malicious agent cannot read root's `/proc/<pid>/environ` even after this
# script has spawned the long-running juicefs daemon.
#
# Isolation model
# ---------------
# JuiceFS shares a single metadata DB and R2 bucket across every user. A naive
# `juicefs mount $META_URL /mnt/jfs` exposes the WHOLE filesystem at /mnt/jfs,
# including every other user's prefix — a trivial cross-user data leak the
# moment the sandbox user runs `ls /mnt/jfs/users/`. We avoid that with:
#
#   1. `--subdir /users/$USER_ID` on the primary mount. JuiceFS scopes the
#      kernel-visible tree to that subdirectory; no parent navigation is
#      possible inside the sandbox. A second `--subdir /skills/$USER_ID`
#      mount serves the read-only skills bind (same JuiceFS instance, but
#      isolated to the user's installed-skills subtree).
#   2. `META_PASSWORD` env split — the metadata DB password is consumed by
#      juicefs from the env, NOT spliced into the connection URL passed as
#      argv. `/proc/<juicefs_pid>/cmdline` is world-readable on Linux, so
#      keeping creds out of argv is mandatory even though root's environ is
#      mode 0o400.
#   3. Per-call credential env. The API passes `JFS_META_URL`, `META_PASSWORD`,
#      and the R2 keys via `commands.run(envs=mount_env)` scoped to this one
#      script invocation. They are not in any sandbox-wide envd config.
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
#   JFS_META_URL    - PostgreSQL metadata URL, with NO password (the password
#                     belongs in META_PASSWORD). If unset or unreachable,
#                     mount is skipped and /workspace falls back to ephemeral.
#   META_PASSWORD   - JuiceFS reads this from env; never appears in argv.
#   JFS_R2_KEY      - R2 access key id (forwarded as AWS_ACCESS_KEY_ID).
#   JFS_R2_SECRET   - R2 secret access key (forwarded as AWS_SECRET_ACCESS_KEY).

set -uo pipefail

JFS_MOUNT=/mnt/jfs            # primary mount: scoped to /users/$USER_ID
JFS_SKILLS_MOUNT=/mnt/jfs-skills  # secondary mount: scoped to /skills/$USER_ID, ro
JFS_SYSTEM_MOUNT=/mnt/jfs-system  # shared mount: scoped to /_system (all users), ro
WORKSPACE=/workspace
SANDBOX_USER="${SANDBOX_USER:-user}"
SANDBOX_UID="$(id -u "$SANDBOX_USER" 2>/dev/null || echo 1000)"
SANDBOX_GID="$(id -g "$SANDBOX_USER" 2>/dev/null || echo 1000)"

# Refuse to run as anything but root — the API is supposed to invoke us via
# commands.run(user="root"), so this is a safety net against misconfiguration.
if [[ "$(id -u)" -ne 0 ]]; then
    echo "FATAL: mount.sh must run as root (got uid=$(id -u))" >&2
    exit 2
fi

# If the configured sandbox user doesn't exist, the strip block below silently
# no-ops and we'd quietly skip privilege hardening. Surface that loudly — the
# template invariant is `user` (or whatever SANDBOX_USER was overridden to)
# exists at acquire time. Continuing is safe (`sudo` binary is purged in the
# template) but a WARN here means future template drift gets noticed.
if ! id -u "$SANDBOX_USER" >/dev/null 2>&1; then
    echo "WARN: SANDBOX_USER='$SANDBOX_USER' does not exist; sudo-strip will no-op" >&2
fi

# E2B's post-build configuration step re-adds `user` to sudo with NOPASSWD,
# undoing the strip in build_e2b_template.py. We re-strip on every sandbox
# acquire (mount.sh runs as root before the agent's first tool call), so the
# unprivileged window between sandbox boot and our first invocation is the
# only time `user` ever holds sudo. Idempotent — silently no-ops if `user`
# is already out of every privilege group.
if id -u "$SANDBOX_USER" >/dev/null 2>&1; then
    gpasswd -d "$SANDBOX_USER" sudo  >/dev/null 2>&1 || true
    gpasswd -d "$SANDBOX_USER" wheel >/dev/null 2>&1 || true
fi
rm -f /etc/sudoers.d/*-user /etc/sudoers.d/90-cloud-init-users \
      /etc/sudoers.d/nopasswd-user /etc/sudoers.d/user 2>/dev/null || true
if [[ -f /etc/sudoers ]]; then
    # E2B's per-boot config script appends `user ALL=(ALL:ALL) NOPASSWD: ALL`
    # directly into /etc/sudoers (not a drop-in). Strip every NOPASSWD line
    # referencing the sandbox user or the sudo group on each acquire — the
    # appended rule survives sudoers.d purges otherwise.
    sed -i '/^%sudo[[:space:]].*NOPASSWD/d' /etc/sudoers
    sed -i "/^${SANDBOX_USER}[[:space:]].*NOPASSWD/d" /etc/sudoers
fi

ensure_workspace_writable() {
    mkdir -p "$WORKSPACE" "$WORKSPACE/.gaia/runs"
    chown -R "$SANDBOX_UID:$SANDBOX_GID" "$WORKSPACE" 2>/dev/null || true
    # 0750 lets the sandbox user read+write own files; group/other have no
    # access. Single-uid sandbox today, but tight perms close the door against
    # a future second-uid feature inheriting world-rwx by accident.
    chmod 0750 "$WORKSPACE" "$WORKSPACE/.gaia" "$WORKSPACE/.gaia/runs" 2>/dev/null || true
    return 0
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

# JuiceFS reads its S3-compatible credentials from these standard AWS vars.
# Both are exported here only for the lifetime of THIS script + its child
# juicefs daemon — they never leave the per-call env block the API set.
export AWS_ACCESS_KEY_ID="${JFS_R2_KEY:-}"
export AWS_SECRET_ACCESS_KEY="${JFS_R2_SECRET:-}"

# META_PASSWORD must be set on the env JuiceFS reads, not embedded in argv.
# `/proc/<juicefs_pid>/cmdline` is world-readable on Linux; spliced creds
# would let the unprivileged sandbox user recover the meta DB password
# without ever escalating.
export META_PASSWORD="${META_PASSWORD:-}"

# jfs_launcher.py is a tiny wrapper that flips PR_SET_DUMPABLE=0 on its own
# process and then execvp's juicefs. The flag persists across exec (juicefs
# is not set-uid) and across fork into the daemon child (--background), so
# every juicefs descendant becomes invisible to non-CAP_SYS_PTRACE readers
# of /proc. This is defense-in-depth on top of the sudo strip: even if a
# future change re-grants sudo to the sandbox user, the daemon's environ
# and cmdline stay locked down.
JFS_LAUNCHER="/etc/gaia/jfs_launcher.py"

mount_user_subdir() {
    if mountpoint -q "$JFS_MOUNT"; then
        return 0
    fi
    mkdir -p "$JFS_MOUNT" /var/cache/juicefs
    # --subdir scopes the kernel-visible tree to the user's prefix — every
    # path under $JFS_MOUNT inside the sandbox is rooted at /users/$USER_ID,
    # and there is no way to navigate up to a sibling user.
    # --backup-meta=0 : R2 ListObjects is unsorted; auto-backup would fail.
    # no --writeback  : writeback loses data on sandbox kill — keep durable.
    "$JFS_LAUNCHER" mount \
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
    mkdir -p "$JFS_SKILLS_MOUNT"
    # Read-only mount of /skills/$USER_ID — backs /workspace/skills.
    "$JFS_LAUNCHER" mount \
        --subdir "/skills/$USER_ID" \
        --read-only \
        --backup-meta=0 \
        --cache-dir=/var/cache/juicefs \
        --cache-size=1024 \
        --buffer-size=300 \
        --background \
        "$JFS_META_URL" "$JFS_SKILLS_MOUNT" 2>&1
}

mount_system_subdir() {
    if mountpoint -q "$JFS_SYSTEM_MOUNT"; then
        return 0
    fi
    mkdir -p "$JFS_SYSTEM_MOUNT"
    # Read-only mount of the SHARED /_system subtree (same for every user) —
    # backs /workspace/.system. Per-user workspaces symlink INDEX.md / GUIDE.md
    # / builtin skills into here instead of holding their own copies.
    "$JFS_LAUNCHER" mount \
        --subdir "/_system" \
        --read-only \
        --backup-meta=0 \
        --cache-dir=/var/cache/juicefs \
        --cache-size=1024 \
        --buffer-size=300 \
        --background \
        "$JFS_META_URL" "$JFS_SYSTEM_MOUNT" 2>&1
}

# The per-user subtrees ``/users/$USER_ID`` and ``/skills/$USER_ID`` are
# pre-created on the HOST side before any sandbox command runs — see
# ``ensure_user_workspace`` / ``ensure_user_skills_dir`` in
# apps/api/app/services/storage/juicefs.py. That keeps the brief "full FS
# visible" window out of the sandbox entirely; we never need an unrestricted
# mount in here.

if ! mount_user_subdir; then
    echo "WARN: juicefs user --subdir mount failed (metadata DB or R2 " \
         "unreachable) — falling back to ephemeral /workspace" >&2
    ensure_workspace_writable
    exit 0
fi

# JuiceFS user-subdir mounted at $JFS_MOUNT. Bind-mount it at /workspace so
# downstream paths keep working unchanged.
chown "$SANDBOX_UID:$SANDBOX_GID" "$JFS_MOUNT" 2>/dev/null || true
chmod 0750 "$JFS_MOUNT" 2>/dev/null || true
mkdir -p "$WORKSPACE"
if ! mount --bind "$JFS_MOUNT" "$WORKSPACE"; then
    echo "WARN: bind-mount $JFS_MOUNT → $WORKSPACE failed — " \
         "falling back to ephemeral /workspace" >&2
    ensure_workspace_writable
    exit 0
fi
chown "$SANDBOX_UID:$SANDBOX_GID" "$WORKSPACE" 2>/dev/null || true
chmod 0750 "$WORKSPACE" 2>/dev/null || true

# Optional skills overlay — best-effort. If /skills/$USER_ID doesn't exist or
# the second mount fails, /workspace/skills falls back to the user's own
# materialized executor-skills subdir under /workspace/skills/.
mkdir -p "$WORKSPACE/skills"
chown "$SANDBOX_UID:$SANDBOX_GID" "$WORKSPACE/skills" 2>/dev/null || true
# `mount --bind ... -o ro` is honoured on the bind itself only on newer
# kernels; older kernels silently ignore the flag and require a remount to
# actually mark the bind read-only. The underlying FUSE is `--read-only`
# already (mount_skills_subdir uses --read-only), so writes still fail in
# either case — but pin the bind itself ro explicitly so the read-only
# surface is consistent at every layer.
if mount_skills_subdir && mount --bind "$JFS_SKILLS_MOUNT" "$WORKSPACE/skills"; then
    mount -o remount,bind,ro "$WORKSPACE/skills" 2>/dev/null || true
fi

# Optional shared-system overlay — best-effort. Backs /workspace/.system with the
# single /_system subtree (INDEX.md, GUIDE.md docs, builtin skills). Per-user
# symlinks point here so the bodies aren't copied per user. If /_system doesn't
# exist or the mount fails, per-user workspaces simply keep their own copies.
mkdir -p "$WORKSPACE/.system"
chown "$SANDBOX_UID:$SANDBOX_GID" "$WORKSPACE/.system" 2>/dev/null || true
if mount_system_subdir && mount --bind "$JFS_SYSTEM_MOUNT" "$WORKSPACE/.system"; then
    mount -o remount,bind,ro "$WORKSPACE/.system" 2>/dev/null || true
fi

mkdir -p "$WORKSPACE/.gaia/runs"
chown -R "$SANDBOX_UID:$SANDBOX_GID" "$WORKSPACE/.gaia" 2>/dev/null || true
chmod -R u=rwX,g=,o= "$WORKSPACE/.gaia" 2>/dev/null || true
mkdir -p "$WORKSPACE/pinned" "$WORKSPACE/settings"
chown "$SANDBOX_UID:$SANDBOX_GID" "$WORKSPACE/pinned" "$WORKSPACE/settings" 2>/dev/null || true
chmod 0750 "$WORKSPACE/pinned" "$WORKSPACE/settings" 2>/dev/null || true
echo "OK: JuiceFS mounted (subdir-scoped); /workspace is durable" >&2
