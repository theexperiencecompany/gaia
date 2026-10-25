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
#   cli-release-images   Does HEAD release the CLI? Its gaia + gaia-web images
#                        must then be published even when nx sees api/web
#                        unaffected. Writes required=true|false.
#   pin-selfhost-release Wait for the release commit's gaia + gaia-web +
#                        self-host bot :<sha> images and ci.yml's quality
#                        gate on it, then tag them v<CLI version>, the set that
#                        CLI release's `gaia update` pins.
#   cli-beta-release     Create the cli-v<beta> GitHub Release as a
#                        prerelease, or mark an existing one; release-please
#                        owns every stable release, so a stable tag is refused.
#   selfhost-bots-arm64  Build the self-host bot images for linux/arm64 and
#                        push them by digest, untagged. Writes digests to
#                        $GITHUB_OUTPUT.
#   selfhost-bots-manifest Fold those arm64 digests and the release's amd64
#                        bot images into multi-arch :<sha> indexes, the tag
#                        pin-selfhost-release waits for.
#   connect-cross-check  Cross-compile tools/gaia-connect for every published
#                        target and discard the result — the pre-merge proof
#                        that a release build cannot fail on a target the
#                        runner does not run.
#   connect-binaries     Cross-compile tools/gaia-connect for every published
#                        target and attach the binaries + a sha256sum manifest
#                        to the cli-v<version> GitHub Release.
#   selfhost-bundle      Build gaia-selfhost-<version>.tar.gz (the compose
#                        files and Caddyfile a self-host install runs, plus a
#                        manifest) and its .sha256, and attach both to the
#                        cli-v<version> GitHub Release.
#   disable-cf-builds    Probe Cloudflare for a Git-connected Workers Build and
#                        say how to disconnect it (dashboard-only API).
#
# Env contract:
#   resolve-image-tags    VERSION_SCHEME, APPS_RELEASE_OUTCOME,
#                         BOTS_RELEASE_OUTCOME (required); GITHUB_OUTPUT.
#   promote-latest        WEB_IMAGE_TAG / GRAFANA_IMAGE_TAG — the immutable tag
#                         pushed by this run's build phase; empty means that
#                         image wasn't built this run. Needs a GHCR login.
#   dispatch-cli-publish  GH_TOKEN (actions:write), TAG, VERSION, SHA (required).
#   cli-release-images    GITHUB_OUTPUT; full history (HEAD^ must exist);
#                         RELEASE_IMAGES=true (optional) requires the images
#                         for any commit (build.yml's release_images input).
#   cli-beta-release      GH_TOKEN (contents:write), RELEASE_TAG (required).
#   selfhost-bots-arm64   GIT_COMMIT_SHA (required); GITHUB_OUTPUT. Needs a
#                         GHCR login and an arm64 buildx builder.
#   selfhost-bots-manifest BOTS_TAG, COMMIT_SHA, ARM64_DIGESTS (required; the
#                         digests output of selfhost-bots-arm64). Needs a
#                         GHCR login.
#   pin-selfhost-release  VERSION, SHA (required; HEAD must be SHA);
#                         GH_TOKEN (actions:read), GITHUB_REPOSITORY;
#                         PIN_WAIT_SECONDS (default 1800), PIN_POLL_SECONDS
#                         (default 30). Needs a GHCR login.
#   connect-cross-check   none.
#   connect-binaries      GH_TOKEN (contents:write), RELEASE_TAG (required);
#                         OUT_DIR (optional, default tools/gaia-connect/dist).
#   selfhost-bundle       VERSION (required); OUT_DIR (optional, default
#                         dist/selfhost); RELEASE_TAG (optional: cli-v<VERSION>,
#                         uploads; needs GH_TOKEN contents:write); DRY_RUN=1
#                         builds and names the upload without making it.
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
# the scheme is production. The outputs are empty when that group was not
# released this run (the deploy then falls back to :latest via the compose
# file's ${VAR:-latest} defaults).
cmd_resolve_image_tags() {

  : "${VERSION_SCHEME:?VERSION_SCHEME is required}"
  : "${APPS_RELEASE_OUTCOME:?APPS_RELEASE_OUTCOME is required}"
  : "${BOTS_RELEASE_OUTCOME:?BOTS_RELEASE_OUTCOME is required}"

  # The tag shape each nx.json versionScheme produces, anchored so :latest and
  # the other scheme's tags never match. Branch runs resolve their develop tag
  # too: the multi-arch API manifest needs it, and deploys stay master-only.
  local TAG_RE
  case "$VERSION_SCHEME" in
    production) TAG_RE='^[0-9]{4}\.[0-9]{2}\.[0-9a-f]{6,12}$' ;;
    develop) TAG_RE='^develop-[0-9a-f]{6,12}$' ;;
    *)
      echo "::error::release: unknown VERSION_SCHEME '$VERSION_SCHEME'" >&2
      return 1
      ;;
  esac

  # Prints the group's tag on stdout (empty = group not released). Fails loud
  # when a released group's local images carry no/ambiguous/mismatched
  # tags of this run's scheme, or when the tag cannot be made to exist in GHCR — a deploy
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
        echo "::error::release: $group released but $GHCR_NAMESPACE/$repo has no local $VERSION_SCHEME tag matching $TAG_RE" >&2
        return 1
      fi
      if [[ "$(echo "$candidates" | wc -l)" -ne 1 ]]; then
        echo "::error::release: $GHCR_NAMESPACE/$repo has multiple $VERSION_SCHEME tags locally: $(echo "$candidates" | tr '\n' ' ')" >&2
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

  local apps_tag bots_tag
  apps_tag=$(resolve_group apps "$APPS_RELEASE_OUTCOME" "${APPS_IMAGE_REPOS[@]}")
  bots_tag=$(resolve_group bots "$BOTS_RELEASE_OUTCOME" "${BOTS_IMAGE_REPOS[@]}")

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
  : "${SHA:?SHA is required (the release commit)}"

  local WORKFLOW="publish-cli.yml"
  local PACKAGE="@heygaia/cli"
  local POLL_SECONDS=20
  # npm publish is the last job: gaia-connect binaries (~15 min), then the
  # image pin's wait for the release commit's build (<= 30 min), then npm.
  local TIMEOUT_SECONDS=3600
  # npm's registry read lags a publish by up to a minute; a finished run is
  # judged only after the read has had that long to catch up.
  local REGISTRY_RETRIES=6
  local REGISTRY_RETRY_SECONDS=10

  published() {
    # Exits non-zero when the exact version is absent from the registry.
    npm view "${PACKAGE}@${VERSION}" version >/dev/null 2>&1
  }

  published_after_lag() {
    local attempt
    for ((attempt = 1; attempt <= REGISTRY_RETRIES; attempt++)); do
      published && return 0
      sleep "$REGISTRY_RETRY_SECONDS"
    done
    return 1
  }

  # Counts publish runs that have not finished yet — any run, not just one we
  # started. It only ever makes us wait longer, never mistake someone else's
  # result for ours. A failed read fails here: read as 0, one API blip made a
  # running publish look finished.
  active_runs() {
    gh run list --workflow "$WORKFLOW" --limit 20 --json status \
      --jq '[.[] | select(.status != "completed")] | length'
  }

  if published; then
    ci_ok "${PACKAGE}@${VERSION} is already on npm — nothing to dispatch."
    return 0
  fi

  echo "Dispatching $WORKFLOW for $TAG ($VERSION)"
  gh workflow run "$WORKFLOW" --ref master -f "tag=$TAG" -f "version=$VERSION" -f "sha=$SHA"

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

    if ! active=$(active_runs); then
      ci_warn "could not list ${WORKFLOW} runs — polling again"
      continue
    fi
    if ((active > 0)); then
      # A publish is still running; keep waiting for it to land.
      seen_active=1
    elif ((seen_active == 1)); then
      # We watched a publish run start and finish. Still absent once the
      # registry read has had time to catch up, that is a failed publish,
      # reported now rather than at the timeout.
      if published_after_lag; then
        ci_ok "${PACKAGE}@${VERSION} published."
        return 0
      fi
      ci_die "Publish finished but ${PACKAGE}@${VERSION} is not on npm. See ${runs_url}"
    fi
  done

  ci_die "Timed out after ${TIMEOUT_SECONDS}s waiting for ${PACKAGE}@${VERSION} on npm. See ${runs_url}"
}

# Whether a CLI version is a beta (X.Y.Z-beta.N): npm dist-tag beta, a
# prerelease GitHub Release, and a quality gate that may come from its PR.
is_cli_beta() {
  [[ "$1" =~ ^[0-9]+\.[0-9]+\.[0-9]+-beta\.[0-9]+$ ]]
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

# Cross-compiles tools/gaia-connect for the five published targets and attaches
# them, plus a `sha256sum`-format manifest, to the cli-v<version> release the
# npm CLI publishes for. The CLI downloads these assets BY EXACT NAME, so the
# names below and the manifest format are a contract — changing either breaks
# `gaia connect` for every already-released CLI.
#
# One linux runner builds all five: the tool is pure Go (modernc sqlite, and the
# darwin keychain read in decrypt_darwin.go shells out to `security` rather than
# linking Security.framework), so CGO_ENABLED=0 cross-compiles darwin too — no
# macOS runner needed. Verified locally: all five targets build under
# CGO_ENABLED=0 with go 1.26.5.
#
# --clobber makes a rerun idempotent: a re-dispatch of an already-published
# release re-uploads the same assets instead of failing on "asset exists".
# The published targets, in one place: the pre-merge cross-check and the
# release build must agree, or a target can compile in CI and fail at publish.
CONNECT_SRC_DIR="tools/gaia-connect"
CONNECT_TARGETS=(darwin/arm64 darwin/amd64 linux/amd64 linux/arm64 windows/amd64)

# Build every target into $1; the asset names land in CONNECT_ASSETS.
_connect_build_all() {
  local abs_out="$1"
  CONNECT_ASSETS=()
  local target goos goarch name
  ci_group "go build (${#CONNECT_TARGETS[@]} targets, CGO_ENABLED=0)"
  for target in "${CONNECT_TARGETS[@]}"; do
    goos="${target%%/*}"
    goarch="${target##*/}"
    name="gaia-connect-${goos}-${goarch}"
    [[ "$goos" == "windows" ]] && name="${name}.exe"
    echo "building $name"
    # -trimpath strips the runner's absolute paths out of the binary; -s -w drop
    # the symbol and DWARF tables (a download, not a debug target).
    (cd "$CONNECT_SRC_DIR" && CGO_ENABLED=0 GOOS="$goos" GOARCH="$goarch" \
      go build -trimpath -ldflags "-s -w" -o "${abs_out}/${name}" .)
    CONNECT_ASSETS+=("$name")
  done
  ci_endgroup
}

# Proves every published GOOS/GOARCH still compiles, without publishing anything:
# a source file selected only for darwin or windows cannot be caught by the
# runner's native `go build`, and finding out at release time blocks the CLI's
# companion assets.
cmd_connect_cross_check() {
  local tmp
  tmp="$(mktemp -d)"
  _connect_build_all "$tmp"
  rm -rf "$tmp"
  echo "### gaia-connect cross-compile — ✅ ${#CONNECT_ASSETS[@]} targets build (${SECONDS}s)" >> "${GITHUB_STEP_SUMMARY:-/dev/null}"
  ci_ok "gaia-connect: OK (${#CONNECT_ASSETS[@]} targets cross-compile in ${SECONDS}s)"
}

cmd_connect_binaries() {

  : "${GH_TOKEN:?GH_TOKEN is required (contents:write on the release)}"
  : "${RELEASE_TAG:?RELEASE_TAG is required (e.g. cli-v0.5.0)}"

  # The workflow runs release.mjs verify-cli before this (tag, version and
  # package.json must agree); this last check keeps a bare local invocation
  # from uploading to a tag of the wrong shape.
  if [[ ! "$RELEASE_TAG" =~ ^cli-v[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$ ]]; then
    ci_die "RELEASE_TAG '$RELEASE_TAG' must match cli-v<version> (e.g. cli-v0.5.0)"
  fi

  local OUT_DIR="${OUT_DIR:-tools/gaia-connect/dist}"
  local SUMS="gaia-connect-SHA256SUMS"

  rm -rf "$OUT_DIR"
  mkdir -p "$OUT_DIR"
  local ABS_OUT
  ABS_OUT="$(cd "$OUT_DIR" && pwd)"

  _connect_build_all "$ABS_OUT"
  local ASSETS=("${CONNECT_ASSETS[@]}")

  ci_group "sha256sum manifest"
  (cd "$ABS_OUT" && sha256sum "${ASSETS[@]}" | tee "$SUMS")
  ci_endgroup

  ci_group "gh release upload $RELEASE_TAG"
  (cd "$ABS_OUT" && gh release upload "$RELEASE_TAG" "${ASSETS[@]}" "$SUMS" --clobber)
  ci_endgroup

  {
    echo "### gaia-connect binaries — ✅ ${#ASSETS[@]} binaries + \`$SUMS\` attached to \`$RELEASE_TAG\` (${SECONDS}s)"
    printf -- '- `%s`\n' "${ASSETS[@]}"
  } >> "${GITHUB_STEP_SUMMARY:-/dev/null}"

  ci_ok "gaia-connect: OK (${#ASSETS[@]} binaries + $SUMS attached to $RELEASE_TAG in ${SECONDS}s)"
}

# Whether HEAD is a CLI release commit: release-please bumps packages/cli's
# version in the commit it tags cli-v<version>. pin-selfhost-release waits for
# that commit's gaia, gaia-web and self-host bot :<sha> images, so build.yml
# publishes them for a release commit even when nx sees none of them as
# affected (a CLI-only release).
cmd_cli_release_images() {

  : "${GITHUB_OUTPUT:?GITHUB_OUTPUT is required}"

  local required=false
  if [[ "${RELEASE_IMAGES:-false}" == "true" ]]; then
    required=true
  else
    local manifest="packages/cli/package.json" before after
    before=$(git show "HEAD^:$manifest" | jq -r .version)
    after=$(git show "HEAD:$manifest" | jq -r .version)
    [[ "$before" != "$after" ]] && required=true
  fi
  echo "required=$required" >> "$GITHUB_OUTPUT"
  ci_ok "cli-release-images: required=$required"
}

# Gives a CLI release its own immutable image set. `gaia update` pins
# GAIA_VERSION=v<CLI version> for gaia (API + worker), gaia-web and the
# self-host bots together, so each must carry that tag before the CLI reaches
# npm, and each must be the release commit's own build (build.yml tags every
# master build :<sha>). That
# build runs alongside this publish, so the pair is awaited, bounded, and a
# timeout fails loud instead of falling back to whatever :latest is. Nothing is
# tagged until all exist, so a timeout never leaves a partial set. Idempotent:
# an existing v<version> tag is kept, because an install may already run it.
# ci.yml's quality-gate verdict across the runs on <sha> of the given events:
# passed when any run's gate succeeded, failed when every run's gate finished
# otherwise, pending while one is still running or no run exists yet.
ci_quality_gate() {
  local sha="$1"
  shift
  local api="repos/${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}/actions"
  local event event_runs run_ids="" run_id state verdict=pending finished=0 running=0
  # Called inside $(...), where errexit does not reach: every gh call returns
  # its own failure so the caller can die on it.
  for event in "$@"; do
    event_runs=$(gh api "$api/workflows/ci.yml/runs?head_sha=$sha&event=$event" --jq '.workflow_runs[].id') || return 1
    run_ids+=" $event_runs"
  done
  for run_id in $run_ids; do
    state=$(gh api "$api/runs/$run_id/jobs?filter=latest&per_page=100" \
      --jq '.jobs[] | select(.name == "quality-gate") | "\(.status) \(.conclusion)"') || return 1
    case "$state" in
      "completed success") verdict=passed ;;
      completed\ *) finished=1 ;;
      *) running=1 ;;
    esac
  done
  if [[ "$verdict" != passed ]] && ((finished == 1 && running == 0)); then
    verdict=failed
  fi
  echo "$verdict"
}

cmd_pin_selfhost_release() {

  : "${VERSION:?VERSION is required}"
  : "${SHA:?SHA is required (the release commit)}"
  local wait_seconds="${PIN_WAIT_SECONDS:-1800}"
  local poll_seconds="${PIN_POLL_SECONDS:-30}"

  [[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || ci_die "SHA '$SHA' must be a full 40-character commit sha"
  local head
  head=$(git rev-parse HEAD)
  [[ "$head" == "$SHA" ]] || ci_die "checked-out commit $head is not the release commit $SHA"

  local tag="v${VERSION}"
  # A stable release is a master commit, judged by its push run. A beta may be
  # cut from a PR head, whose only gate is that PR's run on the same sha.
  local gate_events=(push)
  is_cli_beta "$VERSION" && gate_events+=(pull_request)
  local repo pending=()
  for repo in gaia "$WEB_IMAGE_REPO" "${SELFHOST_BOT_IMAGE_REPOS[@]}"; do
    if docker buildx imagetools inspect "$GHCR_NAMESPACE/$repo:$tag" >/dev/null 2>&1; then
      ci_ok "$GHCR_NAMESPACE/$repo:$tag already exists; keeping it."
    else
      pending+=("$repo")
    fi
  done

  # build.yml publishes :<sha> before ci.yml's quality gate has judged the
  # commit, so the images alone do not say the release commit is green.
  local deadline=$((SECONDS + wait_seconds))
  local missing gate
  while :; do
    missing=()
    for repo in ${pending[@]+"${pending[@]}"}; do
      if ! docker buildx imagetools inspect "$GHCR_NAMESPACE/$repo:$SHA" >/dev/null 2>&1; then
        missing+=("$GHCR_NAMESPACE/$repo:$SHA")
      fi
    done
    gate=$(ci_quality_gate "$SHA" "${gate_events[@]}") ||
      ci_die "could not read ci.yml's runs for $SHA from the Actions API (GH_TOKEN needs actions:read)."
    if [[ "$gate" == failed ]]; then
      ci_die "ci.yml's quality gate failed on $SHA; a release commit must pass it. Fix master and cut the release from a green commit."
    fi
    [[ "$gate" == passed ]] && ((${#missing[@]} == 0)) && break
    if ((SECONDS >= deadline)); then
      [[ "$gate" == passed ]] || ci_die "Timed out after ${wait_seconds}s waiting for ci.yml's quality gate to pass on $SHA (a run cancelled by a newer master push needs a re-run: gh run rerun <id>), then re-dispatch this publish."
      ci_die "Timed out after ${wait_seconds}s waiting for ${missing[*]}. build.yml publishes them for the release commit: re-run the master run for $SHA, then re-dispatch this publish."
    fi
    echo "Waiting for: quality gate ${gate}${missing[*]:+, ${missing[*]}}"
    sleep "$poll_seconds"
  done

  for repo in ${pending[@]+"${pending[@]}"}; do
    echo "Tagging $GHCR_NAMESPACE/$repo:$SHA as :$tag"
    docker buildx imagetools create -t "$GHCR_NAMESPACE/$repo:$tag" "$GHCR_NAMESPACE/$repo:$SHA"
  done
  echo "### Self-host release pinned: \`GAIA_VERSION=$tag\` (images of \`$SHA\`)" >> "${GITHUB_STEP_SUMMARY:-/dev/null}"
}

# A beta has no release-please release, so its publish creates one, marked
# prerelease so neither GitHub's "latest release" nor connect.sh's newest
# stable cli-v* lookup ever lands on it. Idempotent across re-dispatches.
cmd_cli_beta_release() {

  : "${GH_TOKEN:?GH_TOKEN is required}"
  : "${RELEASE_TAG:?RELEASE_TAG is required (e.g. cli-v0.7.0-beta.1)}"

  local version="${RELEASE_TAG#cli-v}"
  [[ "$RELEASE_TAG" == cli-v* ]] && is_cli_beta "$version" ||
    ci_die "RELEASE_TAG '$RELEASE_TAG' is not a CLI beta (cli-vX.Y.Z-beta.N); release-please creates stable releases"

  local prerelease
  if prerelease=$(gh release view "$RELEASE_TAG" --json isPrerelease --jq .isPrerelease 2>/dev/null); then
    if [[ "$prerelease" == "true" ]]; then
      ci_ok "$RELEASE_TAG is already a prerelease."
      return 0
    fi
    gh release edit "$RELEASE_TAG" --prerelease --latest=false
    ci_ok "$RELEASE_TAG marked prerelease."
    return 0
  fi
  gh release create "$RELEASE_TAG" --verify-tag --prerelease --latest=false \
    --title "GAIA CLI $version (beta)" \
    --notes "Beta of the GAIA CLI. Install it with: curl -fsSL https://heygaia.io/install.sh | GAIA_CHANNEL=beta sh"
  ci_ok "$RELEASE_TAG created as a prerelease."
}

# Self-hosters run the bots on arm64 too, while production's bot images stay
# amd64-only. Only a CLI release commit builds the arm64 half: nx release keeps
# publishing the amd64 tag the Swarm deploy pins, untouched.
cmd_selfhost_bots_arm64() {

  : "${GIT_COMMIT_SHA:?GIT_COMMIT_SHA is required}"
  : "${GITHUB_OUTPUT:?GITHUB_OUTPUT is required}"
  local repo metadata digest digests=()
  metadata=$(mktemp)
  for repo in "${SELFHOST_BOT_IMAGE_REPOS[@]}"; do
    ci_group "build $GHCR_NAMESPACE/$repo (linux/arm64)"
    docker buildx build \
      --platform linux/arm64 \
      --file apps/bots/Dockerfile \
      --build-arg "BOT_NAME=${repo#gaia-bot-}" \
      --build-arg "GIT_COMMIT_SHA=$GIT_COMMIT_SHA" \
      --cache-from "type=registry,ref=$GHCR_NAMESPACE/$repo:buildcache-arm64" \
      --cache-to "type=registry,ref=$GHCR_NAMESPACE/$repo:buildcache-arm64,mode=max,image-manifest=true,oci-mediatypes=true,compression=zstd" \
      --output "type=image,name=$GHCR_NAMESPACE/$repo,push-by-digest=true,name-canonical=true,push=true" \
      --metadata-file "$metadata" \
      .
    ci_endgroup
    digest=$(jq -r '."containerimage.digest"' "$metadata")
    [[ "$digest" == sha256:* ]] || ci_die "no digest recorded for the $repo arm64 build"
    digests+=("$repo@$digest")
  done
  echo "digests=${digests[*]}" >> "$GITHUB_OUTPUT"
  ci_ok "selfhost-bots-arm64: ${digests[*]}"
}

# Tags each self-host bot :<sha> as an index of the release's amd64 image
# (:<bots tag>, left as it is) and its arm64 digest. Every digest is checked
# before anything is tagged, so a missing one never leaves a partial set.
cmd_selfhost_bots_manifest() {

  : "${BOTS_TAG:?BOTS_TAG is required}"
  : "${COMMIT_SHA:?COMMIT_SHA is required}"
  : "${ARM64_DIGESTS:?ARM64_DIGESTS is required (selfhost-bots-arm64 did not succeed)}"
  local repo digest digests=()
  for repo in "${SELFHOST_BOT_IMAGE_REPOS[@]}"; do
    digest=$(tr ' ' '\n' <<< "$ARM64_DIGESTS" | sed -n "s|^$repo@||p")
    [[ -n "$digest" ]] || ci_die "no arm64 image for $repo in ARM64_DIGESTS; its :$COMMIT_SHA would be amd64-only"
    digests+=("$digest")
  done
  local i
  for i in "${!SELFHOST_BOT_IMAGE_REPOS[@]}"; do
    repo="${SELFHOST_BOT_IMAGE_REPOS[$i]}"
    docker buildx imagetools create -t "$GHCR_NAMESPACE/$repo:$COMMIT_SHA" \
      "$GHCR_NAMESPACE/$repo:$BOTS_TAG" "$GHCR_NAMESPACE/$repo@${digests[$i]}"
  done
  ci_ok "selfhost-bots-manifest: ${SELFHOST_BOT_IMAGE_REPOS[*]} tagged :$COMMIT_SHA (amd64 + arm64)"
}

# What a self-host install runs from disk, relative to the repo root: the
# compose files (the stack, the code-sandbox and bot overrides) and the files
# they mount or extend. Never docker-compose.build.yml: building needs the
# whole source tree, which a bundle install does not have.
SELFHOST_BUNDLE_GLOBS=(
  infra/docker/docker-compose.selfhost.yml
  infra/docker/docker-compose.sandbox.yml
  "infra/docker/docker-compose.bot-*.yml"
  "infra/docker/selfhost/*"
  infra/docker/seccomp-mongo.json
)
SELFHOST_BUNDLE_MANIFEST="gaia-selfhost.json"

# Builds gaia-selfhost-<version>.tar.gz (+ .sha256) from the checked-out tree;
# with RELEASE_TAG it attaches both to that release, unless DRY_RUN=1.
cmd_selfhost_bundle() {

  : "${VERSION:?VERSION is required (e.g. 0.7.0 or 0.7.0-beta.4)}"
  [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$ ]] ||
    ci_die "VERSION '$VERSION' must be X.Y.Z or X.Y.Z-beta.N"
  if [[ -n "${RELEASE_TAG:-}" && "$RELEASE_TAG" != "cli-v$VERSION" ]]; then
    ci_die "RELEASE_TAG '$RELEASE_TAG' is not the release of VERSION $VERSION (cli-v$VERSION)"
  fi

  local root out_dir asset staging
  root="$(cd "$(dirname "$0")/../.." && pwd)"
  out_dir="${OUT_DIR:-dist/selfhost}"
  asset="gaia-selfhost-${VERSION}.tar.gz"
  mkdir -p "$out_dir"
  out_dir="$(cd "$out_dir" && pwd)"
  staging="$(mktemp -d)"

  local pattern file files=()
  for pattern in "${SELFHOST_BUNDLE_GLOBS[@]}"; do
    local matched=0
    # shellcheck disable=SC2086 # the pattern is a glob on purpose
    for file in $(cd "$root" && compgen -G "$pattern"); do
      files+=("$file")
      matched=1
    done
    ((matched)) || ci_die "selfhost-bundle: nothing matches $pattern"
  done
  for file in "${files[@]}"; do
    mkdir -p "$staging/$(dirname "$file")"
    cp "$root/$file" "$staging/$file"
  done
  files+=("$SELFHOST_BUNDLE_MANIFEST")
  local sorted
  sorted="$(printf '%s\n' "${files[@]}" | LC_ALL=C sort)"
  jq -n --arg version "v$VERSION" --arg files "$sorted" \
    '{version: $version, files: ($files | split("\n"))}' \
    > "$staging/$SELFHOST_BUNDLE_MANIFEST"

  # ustar carries no extended attributes, so GNU tar unpacks a macOS-built
  # bundle without warnings; COPYFILE_DISABLE keeps out macOS ._ files.
  # shellcheck disable=SC2086 # one path per line, none with spaces
  COPYFILE_DISABLE=1 tar --format ustar -czf "$out_dir/$asset" -C "$staging" $sorted
  rm -rf "$staging"
  (cd "$out_dir" && sha256sum "$asset" > "$asset.sha256")
  ci_ok "selfhost-bundle: $out_dir/$asset ($(wc -l <<< "$sorted" | tr -d ' ') files)"

  [[ -n "${RELEASE_TAG:-}" ]] || return 0
  if [[ "${DRY_RUN:-}" == "1" ]]; then
    ci_ok "selfhost-bundle: dry run, not uploading: gh release upload $RELEASE_TAG $asset $asset.sha256 --clobber"
    return 0
  fi
  : "${GH_TOKEN:?GH_TOKEN is required (contents:write on the release)}"
  (cd "$out_dir" && gh release upload "$RELEASE_TAG" "$asset" "$asset.sha256" --clobber)
  echo "### self-host bundle — ✅ \`$asset\` + \`$asset.sha256\` attached to \`$RELEASE_TAG\`" >> "${GITHUB_STEP_SUMMARY:-/dev/null}"
  ci_ok "selfhost-bundle: attached $asset to $RELEASE_TAG"
}

usage() {
  sed -n '2,/^# Env contract/p' "$0" >&2
}

main() {
  local sub="${1:-}"
  shift || true
  case "$sub" in
    resolve-image-tags)   cmd_resolve_image_tags "$@" ;;
    promote-latest)       cmd_promote_latest "$@" ;;
    dispatch-cli-publish) cmd_dispatch_cli_publish "$@" ;;
    cli-release-images)   cmd_cli_release_images "$@" ;;
    pin-selfhost-release) cmd_pin_selfhost_release "$@" ;;
    cli-beta-release)     cmd_cli_beta_release "$@" ;;
    selfhost-bots-arm64)  cmd_selfhost_bots_arm64 "$@" ;;
    selfhost-bots-manifest) cmd_selfhost_bots_manifest "$@" ;;
    connect-cross-check) cmd_connect_cross_check "$@" ;;
    connect-binaries)     cmd_connect_binaries "$@" ;;
    selfhost-bundle)      cmd_selfhost_bundle "$@" ;;
    disable-cf-builds)    cmd_disable_cf_builds "$@" ;;
    *)
      echo "release.sh: unknown subcommand '${sub}'" >&2
      usage
      exit 2
      ;;
  esac
}

main "$@"
