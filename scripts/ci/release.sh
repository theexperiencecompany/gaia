#!/usr/bin/env bash
# release.sh — publishing what a green master produced: image tags, :latest
# pointers, the CLI on npm. Deploying those artifacts to production is a
# different concept and lives in deploy.sh.
#
# Subcommands:
#   resolve-image-tags   Resolve the immutable per-commit Docker tags `nx
#                        release` just built and guarantee they exist in GHCR.
#                        Writes apps_tag / bots_tag to $GITHUB_OUTPUT.
#   promote-latest       Re-point :latest for the repos the Swarm deploy does
#                        not own (gaia-web, gaia-grafana), registry-side.
#   dispatch-cli-publish Dispatch the CLI publish workflow and block until the
#                        version is actually on npm.
#   disable-cf-builds    Probe Cloudflare for a Git-connected Workers Build and
#                        say how to disconnect it (dashboard-only API).
#
# Env contract:
#   resolve-image-tags    VERSION_SCHEME, APPS_RELEASE_OUTCOME,
#                         BOTS_RELEASE_OUTCOME (required); GITHUB_OUTPUT.
#   promote-latest        WEB_IMAGE_TAG / GRAFANA_IMAGE_TAG — the immutable tag
#                         pushed by this run's build phase; empty means that
#                         image wasn't built this run. Needs a GHCR login.
#   dispatch-cli-publish  GH_TOKEN (actions:write), TAG, VERSION (required).
#   disable-cf-builds     CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID,
#                         WORKER_NAME (all optional; no token = manual steps).
set -euo pipefail

# shellcheck source=scripts/ci/lib/log.sh
source "$(dirname "$0")/lib/log.sh"
# shellcheck source=scripts/ci/lib/image-repos.sh
source "$(dirname "$0")/lib/image-repos.sh"

# Resolves the immutable per-commit Docker tags that `nx release` just built
# (production versionScheme "{currentDate|YYMM.DD}.{shortCommitSha}", e.g.
# 2608.10.fa2b2a9) and guarantees they exist in GHCR, so the deploy workflow
# can pin the stack to exactly this run's images instead of :latest.
#
# Runs inside build.yml's docker-release job, after the release steps, on the
# same runner that built the images — the tag is read from the local Docker
# image store rather than recomputed, so a change to nx's scheme (or its
# timezone handling) can never silently produce a tag the images don't carry.
#
# VERSION_SCHEME is production | develop; deploys only run from master, where
# the scheme is production, and anything else resolves to empty tags. The
# outputs are empty when that group was not released this run (the deploy then
# falls back to :latest via the compose file's ${VAR:-latest} defaults).
cmd_resolve_image_tags() {

  : "${VERSION_SCHEME:?VERSION_SCHEME is required}"
  : "${APPS_RELEASE_OUTCOME:?APPS_RELEASE_OUTCOME is required}"
  : "${BOTS_RELEASE_OUTCOME:?BOTS_RELEASE_OUTCOME is required}"

  # Production scheme: YYMM.DD.<short sha>. Anchored so :latest and dev tags
  # never match.
  local TAG_RE='^[0-9]{4}\.[0-9]{2}\.[0-9a-f]{6,12}$'

  # Prints the group's tag on stdout (empty = group not released). Fails loud
  # when a released group's local images carry no/ambiguous/mismatched
  # production tags, or when the tag cannot be made to exist in GHCR — a deploy
  # pinned to a missing tag would fail far later, on the Swarm host.
  resolve_group() {
    local group="$1" outcome="$2"
    shift 2
    local repos=("$@")

    if [[ "$outcome" != "success" ]]; then
      echo "release: $group not released this run (outcome: $outcome)" >&2
      echo ""
      return 0
    fi

    local tag="" repo candidates
    for repo in "${repos[@]}"; do
      candidates=$(docker image ls --format '{{.Tag}}' "$GHCR_NAMESPACE/$repo" | grep -E "$TAG_RE" || true)
      if [[ -z "$candidates" ]]; then
        echo "::error::release: $group released but $GHCR_NAMESPACE/$repo has no local production tag matching $TAG_RE" >&2
        return 1
      fi
      if [[ "$(echo "$candidates" | wc -l)" -ne 1 ]]; then
        echo "::error::release: $GHCR_NAMESPACE/$repo has multiple production tags locally: $(echo "$candidates" | tr '\n' ' ')" >&2
        return 1
      fi
      if [[ -z "$tag" ]]; then
        tag="$candidates"
      elif [[ "$tag" != "$candidates" ]]; then
        echo "::error::release: $group repos disagree on the tag ($tag vs $candidates on $repo)" >&2
        return 1
      fi
    done

    # The tag must be pullable at deploy time. nx release normally pushed it
    # already; if it skipped publishing (the first-run fallback the
    # ensure-bot-images step exists for), push the local image now.
    for repo in "${repos[@]}"; do
      local ref="$GHCR_NAMESPACE/$repo:$tag"
      if ! docker manifest inspect "$ref" > /dev/null 2>&1; then
        echo "release: $ref not in GHCR yet — pushing" >&2
        docker push "$ref" >&2
        if ! docker manifest inspect "$ref" > /dev/null 2>&1; then
          echo "::error::release: $ref still missing from GHCR after push" >&2
          return 1
        fi
      fi
    done

    echo "release: $group => $tag" >&2
    echo "$tag"
  }

  local apps_tag="" bots_tag=""
  if [[ "$VERSION_SCHEME" = "production" ]]; then
    apps_tag=$(resolve_group apps "$APPS_RELEASE_OUTCOME" "${APPS_IMAGE_REPOS[@]}")
    bots_tag=$(resolve_group bots "$BOTS_RELEASE_OUTCOME" "${BOTS_IMAGE_REPOS[@]}")
  else
    echo "release: scheme is '$VERSION_SCHEME' (not production) — deploys are disabled off-master, skipping tag resolution"
  fi

  {
    echo "apps_tag=$apps_tag"
    echo "bots_tag=$bots_tag"
  } >> "$GITHUB_OUTPUT"
  ci_ok "resolve-image-tags => apps: '${apps_tag:-<none>}', bots: '${bots_tag:-<none>}'"
}

# Promotes gate-passed images to :latest for the repos the Swarm deploy does
# not own: gaia-web (a self-host package publish, never deployed by us) and
# gaia-grafana when no backend deploy runs to retag it. Registry-side manifest
# aliasing only (`docker buildx imagetools create`) — no layers move.
#
# Backend repos are deliberately absent: their :latest is re-pointed
# exclusively by `deploy.sh retag` after a successful deploy/rollback
# convergence, preserving the ":latest == deployed" invariant.
cmd_promote_latest() {

  local promoted=false

  if [[ -n "${WEB_IMAGE_TAG:-}" ]]; then
    echo "Pointing $GHCR_NAMESPACE/$WEB_IMAGE_REPO:latest -> :$WEB_IMAGE_TAG"
    docker buildx imagetools create \
      -t "$GHCR_NAMESPACE/$WEB_IMAGE_REPO:latest" \
      "$GHCR_NAMESPACE/$WEB_IMAGE_REPO:$WEB_IMAGE_TAG"
    promoted=true
  fi

  if [[ -n "${GRAFANA_IMAGE_TAG:-}" ]]; then
    echo "Pointing $GHCR_NAMESPACE/$GRAFANA_IMAGE_REPO:latest -> :$GRAFANA_IMAGE_TAG"
    docker buildx imagetools create \
      -t "$GHCR_NAMESPACE/$GRAFANA_IMAGE_REPO:latest" \
      "$GHCR_NAMESPACE/$GRAFANA_IMAGE_REPO:$GRAFANA_IMAGE_TAG"
    promoted=true
  fi

  if [[ "$promoted" = "false" ]]; then
    ci_ok "promote-latest: no image tags to promote (neither web nor grafana was built this run)."
  fi
}

# Dispatches the CLI publish workflow and blocks until the version is on npm.
#
# createWorkflowDispatch returns 204 the moment GitHub *accepts* the request,
# so a fire-and-forget dispatch reports success even when the publish it
# started fails. That is exactly how @heygaia/cli sat unpublished for five
# consecutive releases while Release Please stayed green.
#
# The dispatch API returns no run id, and nothing in a run's metadata ties it
# back to the caller — so any attempt to pick "our" run out of the recent list
# is a guess that a concurrent dispatch (a manual catch-up publish during a
# release, say) silently breaks. Instead this waits on the outcome that
# actually matters and that no other run can fake: the version being on npm.
# Run identity never enters into it.
cmd_dispatch_cli_publish() {

  : "${GH_TOKEN:?GH_TOKEN is required}"
  : "${TAG:?TAG is required}"
  : "${VERSION:?VERSION is required}"

  local WORKFLOW="publish-cli.yml"
  local PACKAGE="@heygaia/cli"
  local POLL_SECONDS=20
  local TIMEOUT_SECONDS=900

  published() {
    # Exits non-zero when the exact version is absent from the registry.
    npm view "${PACKAGE}@${VERSION}" version >/dev/null 2>&1
  }

  # Counts publish runs that have not finished yet — any run, not just one we
  # started. It only ever makes us wait longer, never mistake someone else's
  # result for ours.
  active_runs() {
    gh run list --workflow "$WORKFLOW" --limit 20 --json status \
      --jq '[.[] | select(.status != "completed")] | length' 2>/dev/null || echo 0
  }

  if published; then
    ci_ok "${PACKAGE}@${VERSION} is already on npm — nothing to dispatch."
    return 0
  fi

  echo "Dispatching $WORKFLOW for $TAG ($VERSION)"
  gh workflow run "$WORKFLOW" --ref master -f "tag=$TAG" -f "version=$VERSION"

  local runs_url="${GITHUB_SERVER_URL:-https://github.com}/${GITHUB_REPOSITORY:-theexperiencecompany/gaia}/actions/workflows/${WORKFLOW}"
  local deadline=$((SECONDS + TIMEOUT_SECONDS))
  local seen_active=0
  local active

  while ((SECONDS < deadline)); do
    sleep "$POLL_SECONDS"

    if published; then
      ci_ok "${PACKAGE}@${VERSION} published."
      return 0
    fi

    active=$(active_runs)
    if ((active > 0)); then
      # A publish is still running; keep waiting for it to land.
      seen_active=1
    elif ((seen_active == 1)); then
      # We watched a publish run start and finish, and the version still is not
      # on the registry — that is a failed publish, reported now rather than at
      # the timeout.
      ci_die "Publish finished but ${PACKAGE}@${VERSION} is not on npm. See ${runs_url}"
    fi
  done

  ci_die "Timed out after ${TIMEOUT_SECONDS}s waiting for ${PACKAGE}@${VERSION} on npm. See ${runs_url}"
}

# Best-effort probe/disable for Cloudflare Workers Builds. If a Git-connected
# Build is found, this tells you to disconnect it in the dashboard (the
# underlying API is dashboard-only for many accounts and may 404 — expected).
cmd_disable_cf_builds() {

  local ACCOUNT_ID="${CLOUDFLARE_ACCOUNT_ID:-d65fe47d4d3b4f2725e87b91c772cbc3}"
  local WORKER_NAME="${WORKER_NAME:-gaia}"
  local TOKEN="${CLOUDFLARE_API_TOKEN:-}"

  if [[ -z "$TOKEN" ]]; then
    echo "CLOUDFLARE_API_TOKEN not set — cannot query Cloudflare API."
    echo "Set it and re-run, or perform the manual dashboard step:"
    echo "  Workers & Pages → $WORKER_NAME → Settings → Builds → Disconnect / Disable automatic builds"
    ci_ok "See docs/cloudflare-workers-builds.md"
    return 0
  fi

  echo "Account: ${ACCOUNT_ID:0:6}…  Worker: $WORKER_NAME"
  echo "Probing Cloudflare API (best-effort, 404 is expected if Builds is dashboard-only)…"
  echo ""

  probe() {
    local path="$1"
    echo "GET $path"
    curl -sS -H "Authorization: Bearer $TOKEN" "https://api.cloudflare.com/client/v4$path" \
      | python3 -c "import sys,json; d=json.load(sys.stdin); print(json.dumps(d, indent=2)[:6000])" 2>&1 | head -n 120 || true
    echo ""
  }

  # Known / plausible endpoints (any may 404 depending on account plan)
  probe "/accounts/${ACCOUNT_ID}/workers/scripts/${WORKER_NAME}"
  probe "/accounts/${ACCOUNT_ID}/workers/services/${WORKER_NAME}"
  probe "/accounts/${ACCOUNT_ID}/workers/services/${WORKER_NAME}/environments/production"

  echo "—"
  echo "If any response shows a \"build_config\", \"source\", or \"git\" with a connected repo, disable it:"
  echo "  https://dash.cloudflare.com → Workers & Pages → $WORKER_NAME → Settings → Builds → Disconnect"
  echo "Docs: https://developers.cloudflare.com/workers/ci-cd/builds/"
  echo ""
  echo "Also try dashboard API (may require additional token scopes):"
  echo "  curl -H \"Authorization: Bearer \$TOKEN\" https://api.cloudflare.com/client/v4/accounts/\$ACCOUNT_ID/workers/builds 2>&1 | head"
  echo ""
  ci_ok "After disconnecting, pushes to master should trigger ONLY the GitHub workflow Deploy Web (Cloudflare)."
}

usage() {
  sed -n '2,16p' "$0" >&2
}

main() {
  local sub="${1:-}"
  shift || true
  case "$sub" in
    resolve-image-tags)   cmd_resolve_image_tags "$@" ;;
    promote-latest)       cmd_promote_latest "$@" ;;
    dispatch-cli-publish) cmd_dispatch_cli_publish "$@" ;;
    disable-cf-builds)    cmd_disable_cf_builds "$@" ;;
    *)
      echo "release.sh: unknown subcommand '${sub}'" >&2
      usage
      exit 2
      ;;
  esac
}

main "$@"
