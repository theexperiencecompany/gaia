#!/usr/bin/env bash
# The review stack: one seeded local API that both builds read, and one
# production build per side. Every step fails loud.
#
#   stack.sh tree   <label> <git-ref>   check out <ref> into $REVIEW_HOME/<label> and install
#   stack.sh api                        start the API (+ scripted LLM stub) from the "before" tree
#   stack.sh build  <label>             production `next build` with CI's public build values
#   stack.sh serve  <label>             `next start` the build on its fixed port
#   stack.sh stop   [<label>|api]       stop what `serve`/`api` started
#   stack.sh status
#
# Labels are "before" (v2) and "after" (v3). Ports are fixed so a capture is
# repeatable: API 8100, stub 9810, before 3210, after 3211. Both web origins are
# localhost, which the API's local-development CORS policy allows.
set -euo pipefail

REVIEW_HOME="${REVIEW_HOME:-$HOME/v3review}"
GIT_SOURCE="${GIT_SOURCE:-$HOME/gaia-3bundle}"
API_PORT=8100
STUB_PORT=9810
REVIEW_USER="${REVIEW_USER:-review@gaia.local}"
RUN="$REVIEW_HOME/run"
export PATH="$HOME/.local/bin:$HOME/.local/share/mise/shims:/opt/homebrew/bin:/usr/local/bin:$PATH"
export COREPACK_ENABLE_DOWNLOAD_PROMPT=0 NX_NO_CLOUD=true
mkdir -p "$RUN"

die() { echo "stack.sh: $*" >&2; exit 1; }
web_port() { case "$1" in before) echo 3210 ;; after) echo 3211 ;; *) die "label must be before|after, got '$1'" ;; esac; }
tree_of() { local t="$REVIEW_HOME/$1"; [ -d "$t/apps/web" ] || die "no tree for '$1' at $t — run: stack.sh tree $1 <git-ref>"; echo "$t"; }
wait_http() { # url pid what timeout_s
  local deadline=$(( $(date +%s) + $4 ))
  until curl -s -o /dev/null --max-time 3 "$1"; do
    kill -0 "$2" 2>/dev/null || die "$3 exited while starting (log: $RUN/$3.log)"
    [ "$(date +%s)" -lt "$deadline" ] || die "$3 did not answer at $1 within $4s"
    sleep 1
  done
}
stop_pidfile() { local f="$RUN/$1.pid"; [ -f "$f" ] || return 0; local p; p=$(cat "$f"); kill "$p" 2>/dev/null || true; pkill -P "$p" 2>/dev/null || true; rm -f "$f"; }

cmd_tree() {
  local label="$1" ref="$2" dest="$REVIEW_HOME/$1"
  web_port "$label" >/dev/null
  git -C "$GIT_SOURCE" rev-parse --verify --quiet "$ref^{commit}" >/dev/null || die "$ref is not a commit in $GIT_SOURCE (fetch it or apply a bundle first)"
  if [ -d "$dest" ]; then git -C "$dest" checkout -q --detach "$ref"; else git -C "$GIT_SOURCE" worktree add -q --detach "$dest" "$ref"; fi
  cd "$dest"
  for f in $(git ls-files | grep -E '(^|/)mise\.toml$'); do mise trust -q "$f"; done
  pnpm install --frozen-lockfile
  uv sync --all-packages
  git rev-parse HEAD > "$RUN/$label.sha"
  echo "tree $label = $(cat "$RUN/$label.sha")"
}

cmd_api() {
  local tree; tree=$(tree_of before)
  [ -f "$GIT_SOURCE/apps/api/.env" ] || die "no API env at $GIT_SOURCE/apps/api/.env"
  # The source env minus everything that would reach a real third party from a review run.
  grep -vE '^(POSTHOG_PROJECT_TOKEN|RESEND_API_KEY|RESEND_AUDIENCE_ID|SLACK_DELIVERY_ALERTS_[A-Z_]+|TELEGRAM_BOT_TOKEN|DISCORD_BOT_TOKEN|KAPSO_[A-Z_]+|OPENROUTER_API_KEY|GOOGLE_API_KEY|DEV_AUTH_BYPASS_EMAIL|WORKOS_[A-Z_]+)=' \
    "$GIT_SOURCE/apps/api/.env" > "$tree/apps/api/.env"
  # The bypass never calls WorkOS, but settings refuse to boot without its keys.
  printf 'WORKOS_API_KEY=review-unused\nWORKOS_CLIENT_ID=review-unused\nWORKOS_COOKIE_PASSWORD=review-unused-cookie-password-32chars-min\n' >> "$tree/apps/api/.env"
  stop_pidfile stub; stop_pidfile api
  # The API venv already carries the stub's two deps (fastapi, uvicorn), so no network install.
  (cd "$tree" && LLM_STUB_PORT=$STUB_PORT exec .venv/bin/python tools/llm-stub/server.py > "$RUN/stub.log" 2>&1) & echo $! > "$RUN/stub.pid"
  (
    cd "$tree/apps/api"
    export ENV=development DEV_AUTH_BYPASS_EMAIL="$REVIEW_USER" GAIA_SIM_MODE=1 \
      OPENROUTER_BASE_URL="http://127.0.0.1:$STUB_PORT/api/v1" \
      HOST="http://localhost:$API_PORT" FRONTEND_URL="http://localhost:$(web_port before)"
    # The rate limiter keys on the client address; browser.mjs gives every page load its own (X-Forwarded-For),
    # so ten parallel review browsers on 127.0.0.1 are ten visitors, not one visitor drawing 429 toasts.
    exec uv run --group backend uvicorn app.main:app --host 127.0.0.1 --port $API_PORT --log-level warning \
      --proxy-headers --forwarded-allow-ips 127.0.0.1
  ) > "$RUN/api.log" 2>&1 & echo $! > "$RUN/api.pid"
  wait_http "http://127.0.0.1:$API_PORT/health" "$(cat "$RUN/api.pid")" api 600
  echo "api up on :$API_PORT (bypass user $REVIEW_USER, sim LLM on :$STUB_PORT)"
}

cmd_build() {
  local label="$1" tree; tree=$(tree_of "$label")
  curl -sf -o /dev/null "http://127.0.0.1:$API_PORT/health" || die "the API must be up and seeded before a build: marketplace and use-case pages prerender from it"
  local key; key=$(cat "$HOME/.turnstile_site_key") || die "no ~/.turnstile_site_key (gh variable get NEXT_PUBLIC_TURNSTILE_SITE_KEY)"
  cd "$tree"
  rm -rf apps/web/.next
  echo "build $label ($(git rev-parse --short HEAD)) $(date +%T)"
  NEXT_PUBLIC_API_BASE_URL="http://localhost:$API_PORT/api/v1/" NEXT_PUBLIC_TURNSTILE_SITE_KEY="$key" \
    NX_PARALLEL=2 nice pnpm exec nx build web --skip-nx-cache > "$RUN/build-$label.log" 2>&1 \
    || { tail -40 "$RUN/build-$label.log"; die "build $label failed (log: $RUN/build-$label.log)"; }
  git rev-parse HEAD > "$RUN/$label.built-sha"
  echo "built $label $(date +%T)"
}

cmd_serve() {
  local label="$1" port tree; port=$(web_port "$label"); tree=$(tree_of "$label")
  [ -f "$tree/apps/web/.next/BUILD_ID" ] || die "no production build for $label — run: stack.sh build $label"
  stop_pidfile "web-$label"
  if lsof -ti "tcp:$port" >/dev/null 2>&1; then die "port $port is held by pid $(lsof -ti tcp:$port | head -1)"; fi
  # output: "standalone" builds are served by their own server.js (`next start` redirect-loops on them),
  # which resolves .next/static and public relative to itself, so both are staged beside it.
  local app="$tree/apps/web/.next/standalone/apps/web"
  [ -f "$app/server.js" ] || die "no standalone server at $app/server.js"
  rm -rf "$app/.next/static" "$app/public"
  cp -R "$tree/apps/web/.next/static" "$app/.next/static"
  cp -R "$tree/apps/web/public" "$app/public"
  # HOSTNAME must be the host the browser uses: on any other, Next proxies the i18n rewrite back
  # through the middleware, which redirects /en/x to /x, forever.
  (cd "$app" && NODE_ENV=production PORT="$port" HOSTNAME=localhost exec node server.js) > "$RUN/web-$label.log" 2>&1 &
  echo $! > "$RUN/web-$label.pid"
  wait_http "http://localhost:$port/about" "$(cat "$RUN/web-$label.pid")" "web-$label" 120
  echo "$label served on http://localhost:$port ($(cat "$tree/apps/web/.next/BUILD_ID"))"
}

cmd_stop() {
  case "${1:-all}" in
    api) stop_pidfile api; stop_pidfile stub ;;
    before|after) stop_pidfile "web-$1" ;;
    all) stop_pidfile web-before; stop_pidfile web-after; stop_pidfile api; stop_pidfile stub ;;
    *) die "stop: unknown target '$1'" ;;
  esac
}

cmd_status() {
  for p in api stub web-before web-after; do
    if [ -f "$RUN/$p.pid" ] && kill -0 "$(cat "$RUN/$p.pid")" 2>/dev/null; then echo "$p: running"; else echo "$p: stopped"; fi
  done
  for l in before after; do [ -f "$RUN/$l.built-sha" ] && echo "$l build: $(cat "$RUN/$l.built-sha")"; done
  return 0
}

sub="${1:-}"; shift || true
case "$sub" in
  tree) [ $# -eq 2 ] || die "usage: stack.sh tree <before|after> <git-ref>"; cmd_tree "$@" ;;
  api) cmd_api ;;
  build) [ $# -eq 1 ] || die "usage: stack.sh build <before|after>"; cmd_build "$1" ;;
  serve) [ $# -eq 1 ] || die "usage: stack.sh serve <before|after>"; cmd_serve "$1" ;;
  stop) cmd_stop "${1:-all}" ;;
  status) cmd_status ;;
  *) die "usage: stack.sh tree|api|build|serve|stop|status" ;;
esac
