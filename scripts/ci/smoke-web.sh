#!/usr/bin/env bash
# smoke-web.sh — what search engines see of, and are told about, the deployed marketing site.
#
# Subcommands:
#   audit   Crawl every sitemap URL and every internal link they carry, and fail
#           on what a site audit flags: a non-200 or redirecting sitemap URL, a
#           canonical pointing elsewhere, noindex, a missing title/description,
#           invalid JSON-LD, an hreflang target outside the sitemap, an internal
#           link that redirects or errors, a vanity short link that does not
#           redirect. Also asserts a mirror host carries X-Robots-Tag noindex.
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
# (default https://heygaia.io), SMOKE_MIRROR_URL (default https://cf.heygaia.io),
# SMOKE_REPORT (optional JSON report path). For a local build whose pages name
# production: SMOKE_SITE_URL=https://heygaia.io SMOKE_BASE_URL=http://localhost:3000,
# SMOKE_PER_SITEMAP=N to sample, SMOKE_MIRROR_URL= to skip the mirror check.
# indexnow env: SMOKE_BASE_URL; GITHUB_SHA (default HEAD); GITHUB_REPOSITORY,
# GITHUB_RUN_ID, GH_TOKEN (actions:read), INDEXNOW_DEPLOY_JOB and INDEXNOW_JOB (the
# deploy and IndexNow job names) to find the last notified deployed commit when
# --previous is not given.

set -euo pipefail
# shellcheck source=scripts/ci/lib/log.sh
source "$(dirname "$0")/lib/log.sh"

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

vanity_args() {
  node --input-type=module -e "
    const { vanityRedirects } = await import('$REPO_ROOT/apps/web/vanity-redirects.mjs');
    for (const { source } of vanityRedirects()) console.log('--vanity=' + source);
    for (const route of ['/discord-bot', '/slack-bot']) console.log('--vanity=' + route);
  "
}

cmd_audit() {
  local base="${SMOKE_BASE_URL:-https://heygaia.io}"
  local mirror="${SMOKE_MIRROR_URL-https://cf.heygaia.io}"
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

  if [ -n "$mirror" ]; then
    curl -sSI --retry 3 --retry-all-errors "$mirror/" | grep -qi '^x-robots-tag:.*noindex' \
      || ci_die "smoke-web: $mirror serves without X-Robots-Tag noindex, so the mirror can be indexed"
  fi
  ci_ok "smoke-web: audit OK ($base clean${mirror:+, $mirror noindex})"
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
    indexnow) shift; cmd_indexnow "$@" ;;
    *) echo "usage: $0 audit | indexnow [--dry-run] [--previous <sha>]" >&2; exit 2 ;;
  esac
}

main "$@"
