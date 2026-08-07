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

# Bounded health probe. A wedged JuiceFS FUSE endpoint (dead/stuck juicefs
# daemon, or a mount that came up while the metadata DB / R2 was misconfigured)
# still registers as a mountpoint, so `mountpoint -q` alone returns success —
# but every I/O against it fails with EIO. `timeout` caps the alive-but-stuck
# case so this probe can't hang the script; falls back to a plain stat when
# `timeout` is unavailable.
workspace_healthy() {
    if command -v timeout >/dev/null 2>&1; then
        timeout 5 stat "$WORKSPACE" >/dev/null 2>&1
    else
        stat "$WORKSPACE" >/dev/null 2>&1
    fi
}

# Fast path — /workspace is already a HEALTHY mount, nothing to do. The health
# probe matters: trusting `mountpoint -q` alone left a wedged mount (EIO on
# every op) stuck forever, because this script exited here and never re-mounted
# across acquires. On a wedged mount, tear down the stale bind + underlying
# JuiceFS mounts and fall through to a clean remount.
if mountpoint -q "$WORKSPACE"; then
    if workspace_healthy; then
        ensure_workspace_writable
        exit 0
    fi
    echo "WARN: /workspace is a wedged mount (I/O error) — tearing down stale mounts and remounting" >&2
    for stale in "$WORKSPACE/skills" "$WORKSPACE/.system" "$WORKSPACE" \
                 "$JFS_SKILLS_MOUNT" "$JFS_SYSTEM_MOUNT" "$JFS_MOUNT"; do
        umount -l "$stale" 2>/dev/null || true
        fusermount -u -z "$stale" 2>/dev/null || true
    done
    pkill -f "juicefs mount" 2>/dev/null || true
    sleep 1
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

# Without R2 creds the mount can only fail; short-circuit to the ephemeral
# fallback now instead of letting `juicefs mount` fail and burning the full
# 45s wait_mounted window (a noticeable acquire stall in local/self-hosted).
if [[ -z "${JFS_R2_KEY:-}" || -z "${JFS_R2_SECRET:-}" ]]; then
    echo "WARN: JFS_R2_KEY/JFS_R2_SECRET not set — falling back to ephemeral /workspace" >&2
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
JFS_LOG=/var/log/juicefs.log

# Launch a juicefs mount as a detached --background daemon.
#
# juicefs 1.3.0 mount ALWAYS forks a watchdog that runs a hard ~10s mountpoint-
# readiness check (checkMountpoint@mount_unix.go). In FOREGROUND the watchdog is
# the parent of the FUSE child and, on timeout, SIGABRTs and KILLS that child — so
# a mount that needs >10s dies outright (this is the opposite of what this script
# assumed for years). The primary RW /users/<id> mount runs a full `NewSession`
# (xorm Sync2 schema validation over every jfs_* table); from an E2B sandbox the
# remote CockroachDB latency (200-750ms/op) makes that take ~30-40s, so foreground
# was killed on every cold acquire → ephemeral /workspace fallback → no skills.
# (The read-only /skills + /_system mounts open a read-only session that skips the
# schema writes, finish in ~3s, and survive — which is why ONLY the user mount,
# and thus the whole durable workspace, was failing.)
#
# With --background juicefs double-forks: the watchdog still aborts at 10s, but the
# DETACHED daemon survives and finishes the slow NewSession seconds later, and
# wait_mounted below is the real readiness gate (matches the host-side approach in
# storage/bootstrap.py _mount). The jfs_launcher PR_SET_DUMPABLE hardening runs
# before exec and persists across the --background fork.
#
# `setsid nohup ... &` is required, NOT optional — both words matter:
#   - setsid: the daemon must run in its OWN session. envd runs mount.sh as a captured
#     command (commands.run); if the long-lived daemon stays in mount.sh's process
#     group, envd holds the command stream open for the daemon's whole lifetime and
#     the API's MOUNT_SCRIPT_TIMEOUT fires even though the mount succeeded.
#   - nohup: setsid makes juicefs the session LEADER, so when its --background
#     supervisor SIGABRTs at the 10s watchdog, the session-leader death would SIGHUP
#     (and wedge) the surviving daemon. nohup makes the daemon ignore SIGHUP so it
#     lives through the abort and finishes NewSession. (setsid WITHOUT nohup wedged
#     the daemon ~half the time; with nohup it survives — verified in an E2B sandbox.)
# The `&` lets the script proceed (the user mount is awaited by wait_mounted below).
launch_juicefs() {
    setsid nohup "$JFS_LAUNCHER" mount --background "$@" </dev/null >>"$JFS_LOG" 2>&1 &
}

# Poll until $1 is a real mountpoint, up to $2 seconds (default 45). The juicefs
# daemon is launched detached-foreground (see launch_juicefs), so this poll —
# not the mount command's exit code — is the real readiness gate: a slow-but-
# successful cold mount is no longer dropped to the ephemeral fallback.
wait_mounted() {
    local secs="${2:-45}"
    while [ "$secs" -gt 0 ]; do
        mountpoint -q "$1" && return 0
        sleep 1
        secs=$((secs - 1))
    done
    return 1
}

# Each launch_*_subdir only STARTS the juicefs daemon (launch_juicefs is
# setsid+&, non-blocking) — it does NOT wait for readiness. The clients are
# independent mounts of the same volume on different mountpoints, each paying
# ~13s of connect + SQL schema-sync; starting them without blocking lets that
# overlap. The wait_mounted + bind for each happens in the main flow below.
# Steady state runs TWO daemons (user RW + skills RO) — the shared /_system
# overlay is served from the template-baked bind, no daemon. Only an older,
# pre-bake template falls back to a third (/_system) juicefs daemon.
#
# Memory: the E2B sandbox has only ~1 GB RAM. --buffer-size is an in-RAM read/
# write buffer, so the old large buffers OOM-killed the mount ~2/3 of the time
# when three daemons ran at once. Keep the buffers small (128+32+32) so they
# coexist in ~1 GB even on the fallback path; reads go host-side in prod so a big
# sandbox buffer buys little.
launch_user_subdir() {
    mountpoint -q "$JFS_MOUNT" && return 0
    mkdir -p "$JFS_MOUNT" /var/cache/juicefs
    # --subdir scopes the kernel-visible tree to /users/$USER_ID — no parent
    # navigation to a sibling user. --backup-meta=0: R2 ListObjects is unsorted.
    # no --writeback: writeback loses data on sandbox kill — keep durable.
    #
    # --no-bgjob: background metadata GC (trash cleanup, unreferenced-slice
    # deletion, stale-session removal) must run on exactly ONE client per volume,
    # not on every sandbox. JuiceFS GC repeatedly scans the whole `sessions` set
    # (SMEMBERS/ZSCORE per session) — running it on every per-user RW mount
    # multiplies that scan by the live-sandbox count and was the dominant source
    # of metadata-engine load. The host-side whole-volume mount (storage/
    # bootstrap.py) is the single GC owner; sandbox clients opt out. (The two
    # read-only mounts below already imply --no-bgjob, but it's set explicitly so
    # the intent survives a future juicefs default change.)
    #
    # Metadata caches (cut the per-op firehose: git/npm/python/rg re-stat the
    # same paths and probe thousands of non-existent ones every run). Safe to
    # raise here because JuiceFS invalidates the mounting client's OWN cache on
    # every local write (verified in pkg/vfs/handle.go invalidateDirHandle +
    # docs "consistency exceptions") — the agent always sees its own files
    # immediately regardless of TTL. The TTLs only bound how long THIS sandbox
    # lags a change made by the HOST mount (uploads). Kept at ~10s so a
    # host-uploaded file is listed within ~10s; reads by exact path are
    # close-to-open and see it instantly (open bypasses cache).
    #   --readdir-cache: kernel readdir caching (TTL tied to --attr-cache; needs
    #     kernel 4.20+, E2B is 5.x). Safe: local creates/deletes invalidate the
    #     dir handle so `ls` shows the agent's own changes at once.
    #   --negative-entry-cache=2: kills the ENOENT storm from module resolution;
    #     small TTL because a path stat'd ENOENT before a host upload stays
    #     "missing" for the TTL (cross-client only).
    #   --open-cache omitted (0): keep close-to-open so host-written content is
    #     never served stale.
    #   --heartbeat=30: halve the session-refresh write rate (default 12s); only
    #     cost is slower stale-session detection, which graceful unmount covers.
    launch_juicefs \
        --subdir "/users/$USER_ID" \
        --no-bgjob \
        --heartbeat=30 \
        --attr-cache=10 \
        --entry-cache=10 \
        --dir-entry-cache=10 \
        --negative-entry-cache=2 \
        --readdir-cache \
        --backup-meta=0 \
        --cache-dir=/var/cache/juicefs \
        --cache-size=2048 \
        --max-uploads=20 \
        --buffer-size=128 \
        "$JFS_META_URL" "$JFS_MOUNT"
}

launch_skills_subdir() {
    mountpoint -q "$JFS_SKILLS_MOUNT" && return 0
    mkdir -p "$JFS_SKILLS_MOUNT"
    # Read-only mount of /skills/$USER_ID — backs /workspace/skills.
    # --read-only already implies --no-bgjob; set explicitly for intent.
    # Skills are near-immutable (change only on a skill install, written
    # host-side), so cache metadata aggressively — a new skill appears within
    # the entry TTL, which is fine since installs precede use. No --heartbeat:
    # read-only mounts don't refresh a session. open-cache stays off so an
    # in-place skill reinstall is never served stale.
    launch_juicefs \
        --subdir "/skills/$USER_ID" \
        --read-only \
        --no-bgjob \
        --attr-cache=300 \
        --entry-cache=120 \
        --dir-entry-cache=120 \
        --negative-entry-cache=30 \
        --backup-meta=0 \
        --cache-dir=/var/cache/juicefs \
        --cache-size=512 \
        --buffer-size=32 \
        "$JFS_META_URL" "$JFS_SKILLS_MOUNT"
}

launch_system_subdir() {
    mountpoint -q "$JFS_SYSTEM_MOUNT" && return 0
    mkdir -p "$JFS_SYSTEM_MOUNT"
    # Read-only mount of the SHARED /_system subtree — backs /workspace/.system.
    launch_juicefs \
        --subdir "/_system" \
        --read-only \
        --backup-meta=0 \
        --cache-dir=/var/cache/juicefs \
        --cache-size=512 \
        --buffer-size=32 \
        "$JFS_META_URL" "$JFS_SYSTEM_MOUNT"
}

# The per-user subtrees ``/users/$USER_ID`` and ``/skills/$USER_ID`` are
# pre-created on the HOST side before any sandbox command runs — see
# ``ensure_user_workspace`` / ``ensure_user_skills_dir`` in
# apps/api/app/services/storage/juicefs.py. That keeps the brief "full FS
# visible" window out of the sandbox entirely; we never need an unrestricted
# mount in here.

# Mount the primary RW /users mount FIRST and ALONE, then the read-only secondaries.
# NOT concurrent: the primary's RW NewSession does a full xorm Sync2 schema validation
# over every jfs_* table, which over high-latency CockroachDB (200ms-2.8s/op from an
# E2B box) takes ~40-60s. Running the two secondary daemons at the same time starves
# that cold-connect and, on slow rounds, the primary daemon wedged after juicefs' own
# 10s watchdog abort and never converged (→ ephemeral /workspace → no skills). Solo,
# the primary mounts reliably; the secondaries are read-only (cheap session, ~3s) and
# only start once /workspace is up, so they add ~3s, not 3× the cold connect.
launch_user_subdir

# Primary /workspace is required. Wait for it; on failure take the ephemeral path.
# 90s: --background lets the daemon survive the 10s watchdog abort and finish the
# slow NewSession; setsid lets commands.run return the instant the mount lands. The
# secondaries below mount in ~3s once started, so the real acquire cost is this
# primary window, well under MOUNT_SCRIPT_TIMEOUT_SECONDS=120 in lifecycle.py.
if ! wait_mounted "$JFS_MOUNT" 90; then
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

# Primary is up. NOW launch the read-only skills overlay concurrently — it opens
# a cheap read-only session and contends with nothing critical from here. (The
# shared-system overlay is the template-baked /etc/gaia/system bind below.)
launch_skills_subdir

# Skills overlay (/workspace/skills) — best-effort. If /skills/$USER_ID doesn't
# exist or the mount fails, /workspace/skills falls back to the materialized subdir.
mkdir -p "$WORKSPACE/skills"
chown "$SANDBOX_UID:$SANDBOX_GID" "$WORKSPACE/skills" 2>/dev/null || true
if wait_mounted "$JFS_SKILLS_MOUNT" 30 && mount --bind "$JFS_SKILLS_MOUNT" "$WORKSPACE/skills"; then
    mount -o remount,bind,ro "$WORKSPACE/skills" 2>/dev/null || true
fi

# Shared-system overlay — best-effort. Backs /workspace/.system with the system
# files (INDEX.md, GUIDE.md docs, builtin skills) that the per-user symlinks
# target. These are static + identical for every user, so we prefer the copy
# BAKED into the E2B template at /etc/gaia/system — a plain read-only bind, no
# JuiceFS client and no per-sandbox metadata-engine session. Older templates
# (pre-bake) have no /etc/gaia/system, so fall back to the JuiceFS /_system mount.
mkdir -p "$WORKSPACE/.system"
chown "$SANDBOX_UID:$SANDBOX_GID" "$WORKSPACE/.system" 2>/dev/null || true
if [[ -d /etc/gaia/system ]]; then
    if mount --bind /etc/gaia/system "$WORKSPACE/.system"; then
        mount -o remount,bind,ro "$WORKSPACE/.system" 2>/dev/null || true
    fi
else
    launch_system_subdir
    if wait_mounted "$JFS_SYSTEM_MOUNT" 30 && mount --bind "$JFS_SYSTEM_MOUNT" "$WORKSPACE/.system"; then
        mount -o remount,bind,ro "$WORKSPACE/.system" 2>/dev/null || true
    fi
fi

mkdir -p "$WORKSPACE/.gaia/runs"
chown -R "$SANDBOX_UID:$SANDBOX_GID" "$WORKSPACE/.gaia" 2>/dev/null || true
chmod -R u=rwX,g=,o= "$WORKSPACE/.gaia" 2>/dev/null || true
mkdir -p "$WORKSPACE/pinned" "$WORKSPACE/settings"
chown "$SANDBOX_UID:$SANDBOX_GID" "$WORKSPACE/pinned" "$WORKSPACE/settings" 2>/dev/null || true
chmod 0750 "$WORKSPACE/pinned" "$WORKSPACE/settings" 2>/dev/null || true
echo "OK: JuiceFS mounted (subdir-scoped); /workspace is durable" >&2
