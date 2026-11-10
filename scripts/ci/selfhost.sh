#!/usr/bin/env bash
# selfhost.sh — the self-host stack an end-to-end lane boots and drives.
#
# Subcommands:
#   prepare        Free runner disk for two image builds and record this
#                  checkout as the CLI's install, so `gaia up` boots it.
#   stub           Start the scripted LLM stub (tools/llm-stub) on this host's
#                  private address. Writes base_url to $GITHUB_OUTPUT.
#   up             Build the CLI from this checkout, run `gaia up --yes
#                  --code-sandbox`, and wait until /health/ready answers 200.
#   mongo <pause|unpause>
#                  Freeze or thaw the stack's MongoDB container.
#   logs           Write every stack container's logs into $OUT_DIR.
#
# Env contract:
#   prepare        GITHUB_ACTIONS (frees disk only on a runner).
#   stub           LLM_STUB_PORT (default 9797), OUT_DIR, GITHUB_OUTPUT.
#   up             IMAGE_TAG (optional: pull gaia + gaia-web at that tag; empty
#                  builds both images from this checkout), WEB_URL (default
#                  http://localhost:3000), READY_TIMEOUT_SECONDS (default 600).
#   mongo          none.
#   logs           OUT_DIR (required).
set -euo pipefail

# shellcheck source=scripts/ci/lib/log.sh
source "$(dirname "$0")/lib/log.sh"

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
COMPOSE_PROJECT="gaia-selfhost"

# Prints the container id of one service of the self-host compose project.
_service_container() {
  local service="$1" id
  id=$(docker ps -aq \
    --filter "label=com.docker.compose.project=$COMPOSE_PROJECT" \
    --filter "label=com.docker.compose.service=$service")
  [[ -n "$id" ]] || ci_die "no $COMPOSE_PROJECT container for service '$service'"
  echo "$id"
}

cmd_prepare() {

  if [[ "${GITHUB_ACTIONS:-}" == "true" ]]; then
    # The API (Rust + Python) and web (Next.js) image builds outgrow the stock
    # runner's free disk; these toolchains are never used by this lane.
    ci_group "free runner disk"
    sudo rm -rf /usr/share/dotnet /usr/local/lib/android /opt/ghc /opt/hostedtoolcache/CodeQL
    df -h /
    ci_endgroup
  fi

  # `gaia up` boots the recorded install; record this checkout so it never clones.
  mkdir -p "$HOME/.gaia"
  printf '{\n  "repoPath": "%s"\n}\n' "$REPO_ROOT" > "$HOME/.gaia/config.json"
  ci_ok "selfhost prepare: install recorded at $REPO_ROOT"
}

cmd_stub() {

  : "${OUT_DIR:?OUT_DIR is required}"
  : "${GITHUB_OUTPUT:?GITHUB_OUTPUT is required}"
  local port="${LLM_STUB_PORT:-9797}"

  # The containers reach the stub through the host's own private address, the
  # same shape as a LAN model server, which self-host allows as a provider.
  local host_ip
  host_ip=$(ip -4 route get 1.1.1.1 | awk '{for (i = 1; i < NF; i++) if ($i == "src") print $(i + 1)}')
  python3 -c 'import ipaddress, sys; sys.exit(0 if ipaddress.ip_address(sys.argv[1]).is_private else 1)' "$host_ip" \
    || ci_die "host address '$host_ip' is not private"

  mkdir -p "$OUT_DIR"
  LLM_STUB_HOST=0.0.0.0 LLM_STUB_PORT="$port" \
    nohup uv run "$REPO_ROOT/tools/llm-stub/server.py" > "$OUT_DIR/llm-stub.log" 2>&1 &

  local deadline=$((SECONDS + 120))
  until curl -fsS "http://$host_ip:$port/health" > /dev/null 2>&1; do
    ((SECONDS < deadline)) || ci_die "llm-stub did not answer on $host_ip:$port within 120s (see llm-stub.log)"
    sleep 2
  done

  echo "base_url=http://$host_ip:$port/api/v1" >> "$GITHUB_OUTPUT"
  ci_ok "llm-stub: serving on http://$host_ip:$port"
}

cmd_up() {

  local web_url="${WEB_URL:-http://localhost:3000}"
  local ready_timeout="${READY_TIMEOUT_SECONDS:-600}"

  ci_group "build the CLI from this checkout"
  pnpm --filter @heygaia/cli run build
  ci_endgroup

  local args=(up --yes --code-sandbox)
  if [[ -n "${IMAGE_TAG:-}" ]]; then
    # The shell environment outranks the compose env file in compose interpolation.
    export GAIA_VERSION="$IMAGE_TAG"
    echo "Pulling gaia + gaia-web at :$IMAGE_TAG"
  else
    args+=(--build)
    echo "Building gaia + gaia-web from this checkout"
  fi

  ci_group "gaia ${args[*]}"
  node "$REPO_ROOT/packages/cli/dist/index.js" "${args[@]}"
  ci_endgroup

  # `gaia up` exits 0 on a readiness timeout; the lane needs a ready stack.
  local deadline=$((SECONDS + ready_timeout)) code
  while :; do
    code=$(curl -s -o /dev/null -w '%{http_code}' "$web_url/health/ready" || true)
    [[ "$code" == "200" ]] && break
    ((SECONDS < deadline)) || ci_die "$web_url/health/ready answered $code for ${ready_timeout}s"
    sleep 5
  done
  ci_ok "selfhost up: $web_url ready"
}

cmd_mongo() {

  local action="${1:-}"
  case "$action" in
    pause | unpause) docker "$action" "$(_service_container mongo)" > /dev/null ;;
    *) ci_die "selfhost.sh mongo: expected pause|unpause, got '$action'" ;;
  esac
  ci_ok "mongo: $action"
}

cmd_logs() {

  : "${OUT_DIR:?OUT_DIR is required}"
  mkdir -p "$OUT_DIR"
  docker ps -a --filter "label=com.docker.compose.project=$COMPOSE_PROJECT" > "$OUT_DIR/containers.txt"
  local id service
  for id in $(docker ps -aq --filter "label=com.docker.compose.project=$COMPOSE_PROJECT"); do
    service=$(docker inspect --format '{{ index .Config.Labels "com.docker.compose.service" }}' "$id")
    docker logs "$id" > "$OUT_DIR/$service.log" 2>&1
  done
  ci_ok "selfhost logs: written to $OUT_DIR"
}

usage() {
  sed -n '2,23p' "$0" >&2
}

main() {
  local sub="${1:-}"
  shift || true
  case "$sub" in
    prepare) cmd_prepare "$@" ;;
    stub)    cmd_stub "$@" ;;
    up)      cmd_up "$@" ;;
    mongo)   cmd_mongo "$@" ;;
    logs)    cmd_logs "$@" ;;
    *)
      echo "selfhost.sh: unknown subcommand '${sub}'" >&2
      usage
      exit 2
      ;;
  esac
}

main "$@"
