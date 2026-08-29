#!/usr/bin/env bash
# bootstrap-runner-user.sh — everything the dedicated runner user does itself.
#
# Run AS the new user, inside a real user session (systemd --user and the
# rootless Docker setuptool need XDG_RUNTIME_DIR and the session bus):
#
#   sudo machinectl shell gaia-ci@ /bin/bash -c 'bash /path/to/bootstrap-runner-user.sh <registration-token>'
#
# Unprivileged, idempotent. Steps:
#   1. rootless Docker (dockerd-rootless-setuptool.sh) as a user unit;
#   2. mise with the pinned Node/Python the runner PATH expects, uv;
#   3. `docker load` the five test images exported by create-runner-user.sh;
#   4. seed each instance's tool cache from ~/_tool-seed (node/uv tarballs the
#      jobs would otherwise download once per instance);
#   5. setup.sh — with the OVERLAP env when the previous user's stack is still
#      serving on this box (temporary runner prefix + labels, +10000 ports), or
#      the defaults once it has been retired.
#
# Env: OVERLAP=1 (default) → temporary names/labels/ports; OVERLAP=0 → canonical.
set -euo pipefail

TOKEN="${1:?registration token required (gh api -X POST repos/<repo>/actions/runners/registration-token --jq .token)}"
OVERLAP="${OVERLAP:-1}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGES_TGZ="${IMAGES_TGZ:-/var/tmp/gaia-ci-test-images.tgz}"
NODE_VERSION="${NODE_VERSION:-22.23.2}"
PYTHON_VERSION="${PYTHON_VERSION:-3.12}"

[[ -n "${XDG_RUNTIME_DIR:-}" && -d "$XDG_RUNTIME_DIR" ]] || { echo "::error::no user session (XDG_RUNTIME_DIR unset) — run via machinectl shell $(id -un)@"; exit 1; }
export PATH="$HOME/.local/bin:$HOME/.local/share/mise/shims:$PATH"

# 1. rootless docker
if ! systemctl --user is-active --quiet docker.service; then
  echo "[bootstrap] installing rootless docker"
  dockerd-rootless-setuptool.sh install
  systemctl --user enable --now docker.service
fi
docker context use rootless >/dev/null 2>&1 || true
docker info --format 'docker: {{.ServerVersion}} rootless={{range .SecurityOptions}}{{if eq . "name=rootless"}}yes{{end}}{{end}}'

# 2. toolchain
if ! command -v mise >/dev/null 2>&1; then
  echo "[bootstrap] installing mise"
  curl -fsSL https://mise.run | sh
fi
mise use -g "node@${NODE_VERSION}" "python@${PYTHON_VERSION}" >/dev/null
export MISE_NODE_COREPACK=1
if ! command -v uv >/dev/null 2>&1; then
  echo "[bootstrap] installing uv"
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
node --version; python3 --version; uv --version

# 3. test images
if [[ -s "$IMAGES_TGZ" ]]; then
  echo "[bootstrap] loading test images from $IMAGES_TGZ"
  gunzip -c "$IMAGES_TGZ" | docker load | tail -n 5
fi

# 4/5. runners
if [[ "$OVERLAP" == "1" ]]; then
  echo "[bootstrap] OVERLAP mode: temporary names, labels and ports (the previous stack keeps serving)"
  export RUNNER_NAME_PREFIX=gaia-ci
  export RUNNER_LABELS=gaia-home-new,16core,home-lab
  export LINT_RUNNER_LABELS=gaia-home-lint-new,16core,home-lab
  export NX_CACHE_PORT=4223 SIDECAR_PORT_BASE=28200
  export GAIA_SHARED_POSTGRES_PORT=35432 GAIA_SHARED_REDIS_PORT=26379 GAIA_SHARED_MONGO_PORT=47017
  export GAIA_SHARED_CHROMA_PORT=28000 GAIA_SHARED_RABBITMQ_PORT=35673
fi
export RUNNER_INSTALL_ROOT="$HOME" RUNNER_LOCAL_CACHE="$HOME/ci-cache"
export RUNNER_PATH="$HOME/.local/share/mise/installs/node/${NODE_VERSION}/bin:$HOME/.local/share/mise/installs/python/${PYTHON_VERSION}/bin:$HOME/.local/bin:$HOME/.local/share/mise/shims:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export GH_TOKEN_FILE="$HOME/.config/gaia-ci/gh.env"
# shellcheck disable=SC1090  # the PAT env file written by create-runner-user.sh
[[ -f "$GH_TOKEN_FILE" ]] && set -a && . "$GH_TOKEN_FILE" && set +a

bash "$SCRIPT_DIR/setup.sh" "$TOKEN"

# 4. tool-cache seed (after setup.sh created the instance dirs)
if [[ -d "$HOME/_tool-seed" ]]; then
  for d in "$HOME"/actions-runner-"${RUNNER_NAME_PREFIX:-gaia-home}"-*/_work; do
    [[ -d "$d" ]] || continue
    [[ -d "$d/_tool" ]] || cp -a "$HOME/_tool-seed" "$d/_tool"
  done
fi
echo "[bootstrap] done"
