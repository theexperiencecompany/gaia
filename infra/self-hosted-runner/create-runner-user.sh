#!/usr/bin/env bash
# create-runner-user.sh — the ONE root step of moving CI to a dedicated user.
#
# Run as the current runner owner (the user whose caches are being copied),
# with sudo available:
#
#   PAT=<fine-grained token> bash create-runner-user.sh
#
# What it does, as root, in a single sudo invocation:
#   1. useradd gaia-ci (no supplementary groups: no sudo, no docker) — Ubuntu's
#      useradd allocates a subuid/subgid range automatically (login.defs
#      SUB_UID_COUNT), which rootless Docker needs;
#   2. loginctl enable-linger so its user units run without a session;
#   3. copy the warm caches (ci-cache minus per-user files, pnpm store, uv
#      cache, one instance's tool cache) into the new home — new inodes,
#      then chown; nothing is moved out of the old home;
#   4. write the fine-grained PAT (Administration: read on the repo, for the
#      runners API) to ~gaia-ci/.config/gaia-ci/gh.env, mode 0600;
#   5. install the nftables isolation (nftables-gaia-ci.nft with the new uid
#      substituted) as /etc/nftables.d/gaia-ci.nft plus a oneshot unit that
#      loads it at boot, and load it now.
# Before the sudo step, as the current user, it exports the five pinned test
# images from the current rootless daemon to a tarball the new user's daemon
# can `docker load` (no re-pull over the uplink).
#
# Idempotent: every step checks before it acts. Nothing in the old user's
# home is deleted here — that is a separate, deliberate step after cutover.
set -euo pipefail

NEW_USER="${NEW_USER:-gaia-ci}"
SRC_HOME="${SRC_HOME:-$HOME}"
PAT="${PAT:?PAT (fine-grained token, Administration: read on the repo) is required}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NFT_SRC="$SCRIPT_DIR/nftables-gaia-ci.nft"
IMAGES_TGZ="${IMAGES_TGZ:-/var/tmp/gaia-ci-test-images.tgz}"
[[ -f "$NFT_SRC" ]] || { echo "::error::$NFT_SRC missing"; exit 1; }

# --- as the current user: export the test images ---------------------------
if [[ ! -s "$IMAGES_TGZ" ]]; then
  echo "[create-user] exporting the pinned test images from this user's daemon → $IMAGES_TGZ"
  # Same pins as scripts/ci/shared-test-services.sh — from the checkout when
  # this runs inside one, else from the copy setup.sh installed in ci-cache.
  SHARED_SRC="$SCRIPT_DIR/../../scripts/ci/shared-test-services.sh"
  [[ -f "$SHARED_SRC" ]] || SHARED_SRC="${RUNNER_LOCAL_CACHE:-$SRC_HOME/ci-cache}/shared-test-services.sh"
  [[ -f "$SHARED_SRC" ]] || { echo "::error::shared-test-services.sh not found (checkout or ci-cache)"; exit 1; }
  mapfile -t IMAGES < <(grep -E '^[A-Z]+_IMAGE=' "$SHARED_SRC" | sed -E 's/^[A-Z_]+="([^"]+)"$/\1/')
  docker save "${IMAGES[@]}" | gzip -1 > "$IMAGES_TGZ"
  chmod 0644 "$IMAGES_TGZ"
fi
ls -lh "$IMAGES_TGZ"

# --- root payload -------------------------------------------------------------
# Written to a private temp file: `sudo -S` takes the password on stdin, so the
# payload cannot travel there too. Invoke as
#   printf '%s\n' "$SUDO_PASSWORD" | PAT=... bash create-runner-user.sh
# (or interactively; sudo prompts on the terminal).
PAYLOAD="$(mktemp)"
chmod 0700 "$PAYLOAD"
trap 'rm -f "$PAYLOAD"' EXIT
cat > "$PAYLOAD" <<'ROOT'
set -euo pipefail
U="$1"; SRC="$2"; NFT_SRC="$3"; PAT="$4"

if ! id "$U" >/dev/null 2>&1; then
  useradd --create-home --shell /bin/bash --comment "GitHub Actions runner (CI only)" "$U"
  echo "[root] created $U"
fi
H="$(getent passwd "$U" | cut -d: -f6)"
UID_NEW="$(id -u "$U")"
# No supplementary groups, ever: not docker (rootless daemon instead), not sudo.
usermod -G "" "$U"
grep -q "^$U:" /etc/subuid || { echo "::error::no subuid range for $U — add one with usermod --add-subuids"; exit 1; }
dpkg -s uidmap docker-ce-rootless-extras docker-buildx-plugin >/dev/null
loginctl enable-linger "$U"

install -d -m 0750 -o "$U" -g "$U" "$H/ci-cache" "$H/.local/share" "$H/.cache" "$H/.config/gaia-ci" "$H/_tool-seed"
# Warm caches: new inodes, then chown. Per-user files are excluded (setup.sh
# regenerates them for the new user).
rsync -a --exclude nx-remote.token --exclude 'hooks/' --exclude 'nx-cache-server/' --exclude '*.sh' \
      --exclude buildkitd.toml --exclude '*.lock' --exclude 'gaia-home-*/' --exclude 'profile-*/' \
      --exclude 'pnpm-store/' --exclude '*.log' "$SRC/ci-cache/" "$H/ci-cache/"
[[ -d "$SRC/.local/share/pnpm" ]] && rsync -aH "$SRC/.local/share/pnpm/" "$H/.local/share/pnpm/"
[[ -d "$SRC/.cache/uv" ]] && rsync -a "$SRC/.cache/uv/" "$H/.cache/uv/"
# uv's wheel cache is symlinks into its own archive dir by ABSOLUTE path;
# copied verbatim they still point into the old home, which the new user
# cannot read ("Failed to read from the distribution cache: Permission
# denied"). Re-point them at the copy.
find "$H/.cache/uv" -type l -lname "$SRC/*" -print0 2>/dev/null | while IFS= read -r -d '' link; do
  target="$(readlink "$link")"
  ln -sfn "${target/#"$SRC"/$H}" "$link"
done
seed="$(ls -d "$SRC"/actions-runner-*/_work/_tool 2>/dev/null | head -n 1 || true)"
[[ -n "$seed" ]] && rsync -a "$seed/" "$H/_tool-seed/"
umask 077
printf 'GH_TOKEN=%s\n' "$PAT" > "$H/.config/gaia-ci/gh.env"
chown -R "$U:$U" "$H"
chmod 0600 "$H/.config/gaia-ci/gh.env"

# Network isolation, keyed on the new uid; loaded now and at every boot.
install -d -m 0755 /etc/nftables.d
sed "s/__CI_UID__/$UID_NEW/" "$NFT_SRC" > /etc/nftables.d/gaia-ci.nft
chmod 0644 /etc/nftables.d/gaia-ci.nft
cat > /etc/systemd/system/gaia-ci-firewall.service <<UNIT
[Unit]
Description=nftables isolation for the CI runner user
DefaultDependencies=no
Before=network-pre.target
Wants=network-pre.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/sh -c 'nft delete table inet gaia_ci 2>/dev/null; nft -f /etc/nftables.d/gaia-ci.nft'
ExecStop=/usr/sbin/nft delete table inet gaia_ci

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now gaia-ci-firewall.service
nft list table inet gaia_ci | head -n 5

echo "[root] done: user=$U uid=$UID_NEW home=$H"
ROOT
sudo -S -p '' bash "$PAYLOAD" "$NEW_USER" "$SRC_HOME" "$NFT_SRC" "$PAT"
