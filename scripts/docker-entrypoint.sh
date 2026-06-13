#!/bin/sh
# Container entrypoint:
#   1. Project secrets (Docker Swarm secrets → env)
#   1b. Resolve Infisical-managed secrets the JuiceFS mount needs (R2 / metadata
#       creds), since the mount runs before the Python app that injects them.
#   2. JuiceFS host-side mount (writes encryption PEM if provided, formats the
#      filesystem on first boot, mounts it at $JUICEFS_HOST_MOUNT_PATH).
#      Skipped transparently when R2/JuiceFS env vars are missing — local dev
#      without R2 still works; the storage helpers no-op when the mount is
#      absent.
#   3. Exec the requested command.

set -e

# ---------------------------------------------------------------------------
# 1. Docker Swarm secrets → env vars
# ---------------------------------------------------------------------------
[ -f /run/secrets/gaia_infisical_token ]                          && export INFISICAL_TOKEN=$(cat /run/secrets/gaia_infisical_token)
[ -f /run/secrets/gaia_infisical_machine_identity_client_id ]     && export INFISICAL_MACHINE_IDENTITY_CLIENT_ID=$(cat /run/secrets/gaia_infisical_machine_identity_client_id)
[ -f /run/secrets/gaia_infisical_machine_identity_client_secret ] && export INFISICAL_MACHINE_IDENTITY_CLIENT_SECRET=$(cat /run/secrets/gaia_infisical_machine_identity_client_secret)
[ -f /run/secrets/gaia_infisical_project_id ]                     && export INFISICAL_PROJECT_ID=$(cat /run/secrets/gaia_infisical_project_id)
[ -f /run/secrets/gaia_metrics_token ]                            && export METRICS_TOKEN=$(cat /run/secrets/gaia_metrics_token)

# ---------------------------------------------------------------------------
# 1b. Resolve Infisical-managed secrets the JuiceFS mount needs
# ---------------------------------------------------------------------------
# The Python app injects Infisical secrets at startup, but the JuiceFS mount in
# section 2 runs here in the entrypoint shell — BEFORE Python — so without this
# it cannot see the R2 / metadata creds (this deployment stores them in
# Infisical, not plaintext env) and silently skips the mount, leaving
# $JUICEFS_HOST_MOUNT_PATH an empty local dir. Reuse the app's own Infisical
# loader so the auth/fetch logic lives in exactly one place (no CLI dependency);
# the resolved values land in a 0600 temp file rather than stdout so the
# structured (NDJSON) app logging the loader emits can't corrupt them. Skipped
# when the creds are already present (local .env / prod env take precedence) or
# when the Infisical bootstrap creds are absent (self-host / contributor dev) —
# the mount gate below then no-ops and the storage layer surfaces a clean
# JuiceFSUnavailable instead of silently shadowing onto the overlay.
if [ -z "${R2_ACCESS_KEY:-}" ] && [ -n "${INFISICAL_TOKEN:-}" ] && [ -n "${INFISICAL_MACHINE_IDENTITY_CLIENT_ID:-}" ]; then
    _jfs_env_file="$(mktemp)"
    if python - "$_jfs_env_file" <<'PY'
import os
import shlex
import sys

from shared.py.secrets import inject_infisical_secrets

try:
    inject_infisical_secrets()
except Exception as exc:
    # Best-effort: if Infisical is unreachable/misconfigured the mount gate
    # below no-ops and the storage layer surfaces a clean JuiceFSUnavailable;
    # the app's own startup injection will raise the authoritative error.
    print(f"[entrypoint] Infisical secret resolution failed: {exc}", file=sys.stderr)

_JFS_KEYS = (
    "R2_ACCOUNT_ID",
    "R2_BUCKET",
    "R2_ACCESS_KEY",
    "R2_SECRET_KEY",
    "JUICEFS_META_URL_TEMPLATE",
    "JFS_ENCRYPTION_KEY",
)
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    for key in _JFS_KEYS:
        value = os.environ.get(key)
        if value:
            handle.write(f"export {key}={shlex.quote(value)}\n")
PY
    then
        . "$_jfs_env_file"
    fi
    rm -f "$_jfs_env_file"
fi

# ---------------------------------------------------------------------------
# 2. JuiceFS host-side mount
# ---------------------------------------------------------------------------
JFS_MOUNT_PATH="${JUICEFS_HOST_MOUNT_PATH:-/mnt/jfs}"
JFS_KEY_FILE="/etc/gaia/jfs-master.pem"

_jfs_required="R2_ACCOUNT_ID R2_BUCKET R2_ACCESS_KEY R2_SECRET_KEY JUICEFS_META_URL_TEMPLATE"
_jfs_can_mount=1
for v in $_jfs_required; do
    eval _val="\${$v:-}"
    if [ -z "$_val" ]; then
        _jfs_can_mount=0
        break
    fi
done

if [ "$_jfs_can_mount" = "1" ] && command -v juicefs >/dev/null 2>&1; then
    META_URL=$(printf '%s' "$JUICEFS_META_URL_TEMPLATE" | sed 's/{shard}/0/g')
    BUCKET_URL="https://${R2_ACCOUNT_ID}.r2.cloudflarestorage.com/${R2_BUCKET}"

    # Materialize the RSA private key (multi-line PEM stored as a single env var)
    if [ -n "${JFS_ENCRYPTION_KEY:-}" ]; then
        mkdir -p "$(dirname "$JFS_KEY_FILE")" 2>/dev/null || true
        printf '%s\n' "$JFS_ENCRYPTION_KEY" > "$JFS_KEY_FILE"
        chmod 600 "$JFS_KEY_FILE"
        ENCRYPT_FLAG="--encrypt-rsa-key $JFS_KEY_FILE"
    else
        ENCRYPT_FLAG=""
    fi

    # Format on first boot. `juicefs status` exits non-zero if the FS is unformatted.
    # R2 credentials ride in AWS_* env vars (juicefs honours them when the
    # --access-key/--secret-key flags are absent) so they don't appear in
    # argv visible to `ps auxww` while format is running.
    if ! juicefs status "$META_URL" >/dev/null 2>&1; then
        echo "[entrypoint] Formatting JuiceFS shard 0 against $BUCKET_URL"
        # shellcheck disable=SC2086
        AWS_ACCESS_KEY_ID="$R2_ACCESS_KEY" \
        AWS_SECRET_ACCESS_KEY="$R2_SECRET_KEY" \
        juicefs format \
            --storage s3 \
            --bucket "$BUCKET_URL" \
            --shards 16 \
            $ENCRYPT_FLAG \
            "$META_URL" gaia-0 \
        || echo "[entrypoint] juicefs format failed (ok if another replica formatted concurrently)"
    fi

    if ! mountpoint -q "$JFS_MOUNT_PATH" 2>/dev/null; then
        mkdir -p "$JFS_MOUNT_PATH" /var/cache/juicefs
        echo "[entrypoint] Mounting JuiceFS at $JFS_MOUNT_PATH"
        # --backup-meta=0 because R2 ListObjects is not S3-sorted (see JuiceFS docs).
        # No --writeback: writeback loses data on container kill, unacceptable for agent writes.
        # `|| echo` keeps a mount failure non-fatal: under `set -e` a FATAL exit
        # (e.g. meta DB unreachable) would abort the entrypoint and crash-loop the
        # container. JuiceFS is best-effort — when it can't mount, the app boots
        # and the storage layer surfaces a clean JuiceFSUnavailable (503) instead.
        juicefs mount \
            --backup-meta=0 \
            --cache-dir=/var/cache/juicefs \
            --cache-size=4096 \
            --max-uploads=20 \
            --background \
            "$META_URL" "$JFS_MOUNT_PATH" \
            || echo "[entrypoint] juicefs mount failed — booting without JuiceFS; storage-backed features (uploads, artifacts) return 503 until it mounts"
    fi
else
    echo "[entrypoint] JuiceFS bootstrap skipped (env not configured or binary missing)"
fi

# ---------------------------------------------------------------------------
# 3. Exec
# ---------------------------------------------------------------------------
exec "$@"
