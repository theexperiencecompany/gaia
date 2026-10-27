#!/usr/bin/env bash
# smoke-web.sh — what search engines see of, and are told about, the deployed marketing site.
#
# Subcommands:
#   audit   Crawl every sitemap URL and every internal link they carry, and fail
#           on what a site audit flags: a non-200 or redirecting sitemap URL, a
#           canonical pointing elsewhere, noindex, a missing title/description,
#           invalid JSON-LD, an hreflang target outside the sitemap, an internal
#           link that redirects or errors, a vanity short link that does not
#           redirect.
#   squirrel
#           Audit the site with squirrelscan (pinned below, sha256-checked) at
#           --level surface, every category, and ratchet it against a baseline
#           (scripts/ci/baselines/squirrel-live.txt by default): a rule with more
#           findings or a category scoring lower fails. The config is
#           config/squirrel.toml plus seoSnippet.json's windows.
#   audit-build
#           Start this checkout's production web build (`next start` on a free port)
#           and run audit and squirrel against it as https://heygaia.io, ratcheted
#           against squirrel-build.txt strictly: an improvement the baseline does not
#           record fails too, so the PR that fixes a finding tightens the line. The PR gate.
#   indexnow
#           Submit to IndexNow the pages this deploy changed: the files changed
#           since the last run whose production deploy succeeded and whose IndexNow
#           job did not fail, mapped to their
#           URLs and split into updated/deleted against the live sitemap. Extra
#           arguments pass through (--dry-run prints the list, --previous <sha>
#           overrides the lookup).
#
# Post-deploy alerting: deploy-web.yml runs both behind the production deploy, so
# a red run never blocks or rolls back the deploy. audit env: SMOKE_BASE_URL
# (default https://heygaia.io), SMOKE_REPORT (optional JSON report path). For a local build whose pages name
# production: SMOKE_SITE_URL=https://heygaia.io SMOKE_BASE_URL=http://localhost:3000,
# SMOKE_PER_SITEMAP=N to sample.
# squirrel env: SMOKE_SITE_URL (default https://heygaia.io), SMOKE_BASE_URL (where
# to fetch it from; when it differs, scripts/ci/lib/origin_proxy.py serves it as the
# site), SMOKE_SQUIRREL_BASELINE (default the live site's), SMOKE_SQUIRREL_UPDATE=1
# to rewrite the baseline instead of checking it, SMOKE_SQUIRREL_STRICT=1 to fail on
# an improvement the baseline does not record,
# SQUIRREL_CACHE (where the binary is kept; default RUNNER_TOOL_CACHE or ~/.cache).
# audit-build builds web first (`nx run web:build`, a cache hit after the lane's
# build step), with the NEXT_PUBLIC_* values the build bakes in already set.
# indexnow env: SMOKE_BASE_URL; GITHUB_SHA (default HEAD); GITHUB_REPOSITORY,
# GITHUB_RUN_ID, GH_TOKEN (actions:read), INDEXNOW_DEPLOY_JOB and INDEXNOW_JOB (the
# deploy and IndexNow job names) to find the last notified deployed commit when
# --previous is not given.

set -euo pipefail
# shellcheck source=scripts/ci/lib/log.sh
source "$(dirname "$0")/lib/log.sh"

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

# squirrelscan release assets, one sha256 per platform (the release's manifest.json).
SQUIRREL_VERSION="0.0.133"
squirrel_sha256() {
  case "$1" in
    linux-x64) echo 218640f509db522b54d1d899aac0ebb6a4defb9b045836cf94f10f8b19435465 ;;
    linux-arm64) echo b77e8e9d1f4c8d451b4ae99080c5668bb3ed398a6ea683511a64513e5f3f7818 ;;
    darwin-x64) echo 2fc517f35688ee04df82d23279d353ce372581fc7f675b8f44dcb6c54c0bedc4 ;;
    darwin-arm64) echo 930adc171230f632cf5f2e48c3ce891151aa5314979059825fe7615e5dd01aa7 ;;
    *) ci_die "smoke-web: no pinned squirrel build for $1" ;;
  esac
}

vanity_args() {
  node --input-type=module -e "
    const { vanityRedirects } = await import('$REPO_ROOT/apps/web/vanity-redirects.mjs');
    for (const { source } of vanityRedirects()) console.log('--vanity=' + source);
    for (const route of ['/discord-bot', '/slack-bot']) console.log('--vanity=' + route);
  "
}

cmd_audit() {
  local base="${SMOKE_BASE_URL:-https://heygaia.io}"
  local -a args=()
  local line
  while IFS= read -r line; do args+=("$line"); done < <(vanity_args)
  [ "${#args[@]}" -gt 0 ] || ci_die "smoke-web: no vanity redirects read from apps/web/vanity-redirects.mjs"
  [ -n "${SMOKE_REPORT:-}" ] && args+=("--out=$SMOKE_REPORT")
  [ -n "${SMOKE_SITE_URL:-}" ] && args+=("--site-url=$SMOKE_SITE_URL")
  [ -n "${SMOKE_PER_SITEMAP:-}" ] && args+=("--per-sitemap=$SMOKE_PER_SITEMAP")

  ci_group "SEO audit of $base"
  local status=0
  python3 -I "$REPO_ROOT/scripts/ci/lib/seo_audit.py" --base "$base" ${args[@]+"${args[@]}"} || status=$?
  ci_endgroup
  [ "$status" -eq 0 ] || ci_die "smoke-web: SEO audit of $base failed (findings above)"
  ci_ok "smoke-web: audit OK ($base clean)"
}

squirrel_platform() {
  local os arch
  case "$(uname -s)" in
    Linux) os=linux ;;
    Darwin) os=darwin ;;
    *) ci_die "smoke-web: squirrel has no build for $(uname -s)" ;;
  esac
  case "$(uname -m)" in
    x86_64 | amd64) arch=x64 ;;
    aarch64 | arm64) arch=arm64 ;;
    *) ci_die "smoke-web: squirrel has no build for $(uname -m)" ;;
  esac
  echo "$os-$arch"
}

sha256_of() {
  if command -v sha256sum >/dev/null; then sha256sum "$1"; else shasum -a 256 "$1"; fi | cut -d' ' -f1
}

# Print the path of the pinned squirrel binary, downloading it once per cache.
install_squirrel() {
  local platform want dir bin
  platform="$(squirrel_platform)"
  want="$(squirrel_sha256 "$platform")"
  dir="${SQUIRREL_CACHE:-${RUNNER_TOOL_CACHE:-$HOME/.cache}/squirrel}/$SQUIRREL_VERSION"
  bin="$dir/squirrel-$platform"
  if [ ! -x "$bin" ] || [ "$(sha256_of "$bin")" != "$want" ]; then
    mkdir -p "$dir"
    curl -fsSL --retry 3 --retry-all-errors -o "$bin.part" \
      "https://github.com/squirrelscan/squirrelscan/releases/download/v$SQUIRREL_VERSION/squirrel-$SQUIRREL_VERSION-$platform"
    [ "$(sha256_of "$bin.part")" = "$want" ] \
      || ci_die "smoke-web: squirrel $SQUIRREL_VERSION ($platform) does not match its pinned sha256"
    chmod +x "$bin.part"
    mv -f "$bin.part" "$bin"
  fi
  echo "$bin"
}

SQUIRREL_WORK=""
PROXY_PID=""
PROXY_URL=""
stop_squirrel() {
  if [ -n "$PROXY_PID" ]; then
    kill "$PROXY_PID" 2>/dev/null || true
    wait "$PROXY_PID" 2>/dev/null || true
  fi
  if [ -n "$SQUIRREL_WORK" ]; then rm -rf "$SQUIRREL_WORK"; fi
}

# Start origin_proxy.py serving $2 as $1; set PROXY_URL once it listens.
start_origin_proxy() {
  local site="$1" base="$2"
  python3 -I "$REPO_ROOT/scripts/ci/lib/origin_proxy.py" --site "$site" --origin "$base" \
    --cert-dir "$SQUIRREL_WORK/certs" --port-file "$SQUIRREL_WORK/proxy.port" >"$SQUIRREL_WORK/proxy.log" 2>&1 &
  PROXY_PID=$!
  for _ in $(seq 1 60); do
    if [ -s "$SQUIRREL_WORK/proxy.port" ]; then
      PROXY_URL="http://127.0.0.1:$(cat "$SQUIRREL_WORK/proxy.port")"
      return 0
    fi
    kill -0 "$PROXY_PID" 2>/dev/null || break
    sleep 0.5
  done
  cat "$SQUIRREL_WORK/proxy.log" >&2
  ci_die "smoke-web: the origin proxy for $base did not start"
}

cmd_squirrel() {
  local site="${SMOKE_SITE_URL:-https://heygaia.io}"
  local base="${SMOKE_BASE_URL:-${SMOKE_SITE_URL:-https://heygaia.io}}"
  local bin status=0
  bin="$(install_squirrel)"
  SQUIRREL_WORK="$(mktemp -d)"
  trap stop_squirrel EXIT
  # Its own HOME: squirrel keeps crawl state and a pinned user agent there per domain.
  mkdir -p "$SQUIRREL_WORK/home"
  python3 -I "$REPO_ROOT/scripts/ci/lib/squirrel.py" config --out "$SQUIRREL_WORK/squirrel.toml"

  local -a run_env=(HOME="$SQUIRREL_WORK/home" SQUIRREL_NO_UPDATE=1)
  if [ "$base" != "$site" ]; then
    start_origin_proxy "$site" "$base"
    run_env+=(HTTPS_PROXY="$PROXY_URL" HTTP_PROXY="$PROXY_URL" NODE_EXTRA_CA_CERTS="$SQUIRREL_WORK/certs/ca.pem")
  fi

  ci_group "squirrel $SQUIRREL_VERSION audit of $site (served from $base)"
  env -C "$SQUIRREL_WORK" "${run_env[@]}" "$bin" -c "$SQUIRREL_WORK/squirrel.toml" audit "$site" \
    --offline --no-publish --level surface --format json -o "$SQUIRREL_WORK/report.json" || status=$?
  if [ -n "$PROXY_PID" ]; then cat "$SQUIRREL_WORK/proxy.log"; fi
  ci_endgroup
  [ "$status" -eq 0 ] || ci_die "smoke-web: squirrel could not audit $site (exit $status, output above)"

  python3 -I "$REPO_ROOT/scripts/ci/lib/squirrel.py" ratchet --report "$SQUIRREL_WORK/report.json" \
    --baseline "${SMOKE_SQUIRREL_BASELINE:-$REPO_ROOT/scripts/ci/baselines/squirrel-live.txt}" \
    ${SMOKE_SQUIRREL_UPDATE:+--update} ${SMOKE_SQUIRREL_STRICT:+--strict} || ci_die "smoke-web: squirrel on $site does not match its baseline (above)"
  ci_ok "smoke-web: squirrel OK ($site within its baseline)"
}

WEB_PID=""
WEB_URL=""
stop_web() {
  if [ -n "$WEB_PID" ]; then kill -TERM -- "-$WEB_PID" 2>/dev/null || true; fi
}

# Start the production build on a free port; set WEB_URL once it is ready.
start_web() {
  local web="$REPO_ROOT/apps/web" log="$1" port
  port="$(node -e "const s=require('net').createServer().listen(0,'127.0.0.1',()=>{console.log(s.address().port);s.close()})")"
  # Its own process group, so next and its workers stop together.
  set -m
  (builtin cd "$web" && exec node_modules/.bin/next start --port "$port" >"$log" 2>&1) &
  WEB_PID=$!
  set +m
  for _ in $(seq 1 120); do
    if grep -q "Ready in" "$log"; then
      WEB_URL="http://127.0.0.1:$port"
      return 0
    fi
    kill -0 "$WEB_PID" 2>/dev/null || break
    sleep 0.5
  done
  cat "$log" >&2
  ci_die "smoke-web: next start did not become ready"
}

cmd_audit_build() {
  local log status=0
  # A cache hit when the lane's build step already built web with the same env.
  ci_group "nx run web:build"
  (builtin cd "$REPO_ROOT" && pnpm exec nx run web:build --output-style=stream)
  ci_endgroup
  log="$(mktemp)"
  trap stop_web EXIT
  start_web "$log"
  export SMOKE_BASE_URL="$WEB_URL" SMOKE_SITE_URL="https://heygaia.io" \
    SMOKE_SQUIRREL_BASELINE="$REPO_ROOT/scripts/ci/baselines/squirrel-build.txt" SMOKE_SQUIRREL_STRICT=1
  # Separate processes: a function run on the left of || ignores set -e.
  bash "$0" audit || status=1
  bash "$0" squirrel || status=1
  [ "$status" -eq 0 ] || ci_die "smoke-web: the production build fails the SEO audit (findings above)"
  ci_ok "smoke-web: audit-build OK (seo audit and squirrel within bounds on the production build)"
}

cmd_indexnow() {
  local base="${SMOKE_BASE_URL:-https://heygaia.io}"
  python3 -I "$REPO_ROOT/scripts/ci/lib/indexnow.py" --repo "$REPO_ROOT" --site "$base" \
    --head "${GITHUB_SHA:-HEAD}" "$@" || ci_die "smoke-web: IndexNow submission for $base failed (above)"
  ci_ok "smoke-web: IndexNow OK ($base)"
}

main() {
  case "${1:-}" in
    audit) cmd_audit ;;
    squirrel) cmd_squirrel ;;
    audit-build) cmd_audit_build ;;
    indexnow) shift; cmd_indexnow "$@" ;;
    *) echo "usage: $0 audit | squirrel | audit-build | indexnow [--dry-run] [--previous <sha>]" >&2; exit 2 ;;
  esac
}

main "$@"
