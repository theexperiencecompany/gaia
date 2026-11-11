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
#           Audit every sitemap page with squirrelscan (pinned below, sha256-checked),
#           every category, links to other sites included on the live site, and hold
#           it to a baseline (scripts/ci/baselines/squirrel-live.txt by default): a
#           finding on a page, check and item the baseline does not list, or a
#           category scoring below its line, fails. A fixed finding or a raised score
#           is dropped from the baseline file in place, for `tighten` to propose. The
#           config is config/squirrel.toml plus seoSnippet.json's windows.
#   audit-build
#           Start this checkout's production web build (`next start` on a free port)
#           and run audit and squirrel against it as https://heygaia.io, squirrel on
#           one page per template per locale plus every page the diff renders, held
#           to squirrel-build.txt on those pages strictly: a fix the baseline does not
#           record fails too, so the PR that fixes a finding drops its line. The PR gate.
#   tighten
#           Open (or update) the PR that commits the baseline a full crawl tightened,
#           when it did.
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
# site), SMOKE_SQUIRREL_PAGES (a file of the URLs to audit instead of every sitemap
# page, which the proxy then serves as the sitemap; only their findings are judged),
# SMOKE_SQUIRREL_BASELINE (default the live site's), SMOKE_SQUIRREL_UPDATE=1
# to rewrite the baseline instead of checking it, SMOKE_SQUIRREL_STRICT=1 to fail on
# an improvement the baseline does not record, GITHUB_OUTPUT (gets `alert`, the
# short message for deploy.sh notify, on a red full crawl),
# SQUIRREL_CACHE (where the binary is kept; default RUNNER_TOOL_CACHE or ~/.cache).
# audit-build serves the web build nx's ci:seo task depends on (web:build), so
# run it as `nx run ci:seo`, with the NEXT_PUBLIC_* values the build bakes in set.
# audit-build env: GAIA_PR_BASE (the base the diff starts from, as changes.sh
# base-rev reads it), SMOKE_SQUIRREL_ALL_PAGES=1 to audit every page (how
# squirrel-build.txt is regenerated, with SMOKE_SQUIRREL_UPDATE=1).
# tighten env: GH_TOKEN (contents and pull-requests write), SMOKE_SQUIRREL_BASELINE.
# indexnow env: SMOKE_BASE_URL; GITHUB_SHA (default HEAD); GITHUB_REPOSITORY,
# GITHUB_RUN_ID, GH_TOKEN (actions:read), INDEXNOW_DEPLOY_WORKFLOW (the workflow file
# that declares the deploy, whose own runs are searched too), INDEXNOW_DEPLOY_JOB and
# INDEXNOW_JOB (the deploy and IndexNow job names it declares) to find the last
# notified deployed commit when --previous is not given.

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

# Start origin_proxy.py serving $2 as $1, extra arguments passed on; set PROXY_URL once it listens.
start_origin_proxy() {
  local site="$1" base="$2"
  shift 2
  python3 -I "$REPO_ROOT/scripts/ci/lib/origin_proxy.py" --site "$site" --origin "$base" \
    --cert-dir "$SQUIRREL_WORK/certs" --port-file "$SQUIRREL_WORK/proxy.port" "$@" >"$SQUIRREL_WORK/proxy.log" 2>&1 &
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
  local baseline="${SMOKE_SQUIRREL_BASELINE:-$REPO_ROOT/scripts/ci/baselines/squirrel-live.txt}"
  local bin pages count status=0
  bin="$(install_squirrel)"
  SQUIRREL_WORK="$(mktemp -d)"
  trap stop_squirrel EXIT
  # Its own HOME: squirrel keeps the crawl there, which the ratchet reads, and a pinned user agent.
  mkdir -p "$SQUIRREL_WORK/home"
  python3 -I "$REPO_ROOT/scripts/ci/lib/squirrel.py" config --out "$SQUIRREL_WORK/squirrel.toml"

  local -a ratchet_args=() proxy_args=()
  if [ -n "${SMOKE_SQUIRREL_PAGES:-}" ]; then
    [ "$base" != "$site" ] || ci_die "smoke-web: SMOKE_SQUIRREL_PAGES needs SMOKE_BASE_URL: only the proxy can serve the list as the sitemap"
    pages="$SMOKE_SQUIRREL_PAGES"
    proxy_args=(--sitemap "$pages")
    ratchet_args+=(--sample)
  else
    pages="$SQUIRREL_WORK/pages.txt"
    python3 -I "$REPO_ROOT/scripts/ci/lib/squirrel.py" pages --all --site "$site" --base "$base" --out "$pages"
    [ -n "${SMOKE_SQUIRREL_UPDATE:-}" ] || ratchet_args+=(--tighten)
  fi
  count="$(grep -c . "$pages")"

  # --level quick crawls the seed and the sitemap's URLs and follows no links, so
  # with --max-pages at the list's length it audits exactly the listed pages.
  local -a run_env=(HOME="$SQUIRREL_WORK/home" SQUIRREL_NO_UPDATE=1 NO_TELEMETRY=1)
  local -a audit_args=(--no-publish --level quick --max-pages "$count" --format json -o "$SQUIRREL_WORK/report.json")
  if [ "$base" != "$site" ]; then
    start_origin_proxy "$site" "$base" ${proxy_args[@]+"${proxy_args[@]}"}
    run_env+=(HTTPS_PROXY="$PROXY_URL" HTTP_PROXY="$PROXY_URL" NODE_EXTRA_CA_CERTS="$SQUIRREL_WORK/certs/ca.pem")
    # The proxy refuses every other host, so links to other sites cannot be checked through it.
    audit_args+=(--offline)
  else
    audit_args+=(--external-links)
  fi

  ci_group "squirrel $SQUIRREL_VERSION audit of $count pages of $site (served from $base)"
  env -C "$SQUIRREL_WORK" "${run_env[@]}" "$bin" -c "$SQUIRREL_WORK/squirrel.toml" audit "$site" \
    "${audit_args[@]}" || status=$?
  if [ -n "$PROXY_PID" ]; then cat "$SQUIRREL_WORK/proxy.log"; fi
  ci_endgroup
  [ "$status" -eq 0 ] || ci_die "smoke-web: squirrel could not audit $site (exit $status, output above)"

  if [ -n "${GITHUB_OUTPUT:-}" ]; then ratchet_args+=(--github-output "$GITHUB_OUTPUT"); fi
  python3 -I "$REPO_ROOT/scripts/ci/lib/squirrel.py" ratchet --site "$site" --home "$SQUIRREL_WORK/home" \
    --report "$SQUIRREL_WORK/report.json" --pages "$pages" --baseline "$baseline" \
    ${ratchet_args[@]+"${ratchet_args[@]}"} ${SMOKE_SQUIRREL_UPDATE:+--update} ${SMOKE_SQUIRREL_STRICT:+--strict} \
    || ci_die "smoke-web: squirrel on $site does not match its baseline (above)"
  ci_ok "smoke-web: squirrel OK ($count pages of $site within their baseline)"
}

WEB_PID=""
WEB_URL=""
stop_web() {
  if [ -n "$WEB_PID" ]; then kill -TERM -- "-$WEB_PID" 2>/dev/null || true; fi
}

# Start the production build on a free port; set WEB_URL once it is ready.
start_web() {
  local web="$REPO_ROOT/apps/web" log="$1" port
  port="$(node -e "const s=require('net').createServer().listen(0,'127.0.0.1',()=>{process.stdout.write(String(s.address().port));s.close()})")"
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

# Print the commit this checkout's diff starts from: where HEAD left the PR's base.
diff_base() {
  if [ "$(git -C "$REPO_ROOT" rev-parse --is-shallow-repository)" = true ]; then
    ci_group "smoke-web: fetch the history the diff needs (shallow checkout)" >&2
    git -C "$REPO_ROOT" fetch --no-tags --unshallow origin >&2
    ci_endgroup >&2
  fi
  local rev
  rev="$(bash "$REPO_ROOT/scripts/ci/changes.sh" base-rev)"
  git -C "$REPO_ROOT" merge-base "$rev" HEAD
}

cmd_audit_build() {
  local log pages previous status=0
  log="$(mktemp)"
  trap stop_web EXIT
  start_web "$log"
  export SMOKE_BASE_URL="$WEB_URL" SMOKE_SITE_URL="https://heygaia.io" \
    SMOKE_SQUIRREL_BASELINE="$REPO_ROOT/scripts/ci/baselines/squirrel-build.txt"
  if [ -z "${SMOKE_SQUIRREL_ALL_PAGES:-}" ]; then
    pages="$(mktemp)"
    previous="$(diff_base)"
    python3 -I "$REPO_ROOT/scripts/ci/lib/squirrel.py" pages --site "$SMOKE_SITE_URL" --base "$WEB_URL" \
      --previous "$previous" --out "$pages"
    export SMOKE_SQUIRREL_PAGES="$pages" SMOKE_SQUIRREL_STRICT=1
  fi
  # Separate processes: a function run on the left of || ignores set -e.
  bash "$0" audit || status=1
  bash "$0" squirrel || status=1
  [ "$status" -eq 0 ] || ci_die "smoke-web: the production build fails the SEO audit (findings above)"
  ci_ok "smoke-web: audit-build OK (seo audit and squirrel within bounds on the production build)"
}

cmd_tighten() {
  local baseline="${SMOKE_SQUIRREL_BASELINE:-$REPO_ROOT/scripts/ci/baselines/squirrel-live.txt}"
  local branch="chore/squirrel-baseline-tighten" existing
  local title="chore(seo): drop the findings the full crawl no longer sees"
  existing="$(gh pr list --head "$branch" --base master --state open --json number --jq '.[0].number')"
  if git -C "$REPO_ROOT" diff --quiet -- "$baseline"; then
    # A baseline PR an earlier crawl opened proposes what this crawl no longer sees.
    if [ -n "$existing" ]; then
      gh pr close "$existing" --delete-branch --comment "The latest full crawl no longer improves on the baseline, so this tightening would fail the next crawl."
    fi
    ci_ok "smoke-web: tighten OK (the crawl fixed nothing the baseline lists)"
    return 0
  fi
  git -C "$REPO_ROOT" config user.name "github-actions[bot]"
  git -C "$REPO_ROOT" config user.email "github-actions[bot]@users.noreply.github.com"
  git -C "$REPO_ROOT" checkout -B "$branch"
  git -C "$REPO_ROOT" add -- "$baseline"
  git -C "$REPO_ROOT" commit -m "$title"
  git -C "$REPO_ROOT" push --force origin "$branch"
  if [ -n "$existing" ]; then
    ci_ok "smoke-web: tighten OK (updated #$existing)"
    return 0
  fi
  gh pr create --base master --head "$branch" --title "$title" \
    --body "The full squirrelscan crawl of the live site no longer sees these findings, or scores a category higher, so its baseline drops them. Opened by \`smoke-web.sh tighten\`; generated by the crawl, not hand-edited."
  ci_ok "smoke-web: tighten OK (opened the baseline PR)"
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
    tighten) cmd_tighten ;;
    indexnow) shift; cmd_indexnow "$@" ;;
    *) echo "usage: $0 audit | squirrel | audit-build | tighten | indexnow [--dry-run] [--previous <sha>]" >&2; exit 2 ;;
  esac
}

main "$@"
