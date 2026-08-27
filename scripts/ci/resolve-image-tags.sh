#!/usr/bin/env bash
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
# Inputs (env):
#   VERSION_SCHEME         production | develop (deploys only run from master,
#                          where the scheme is production; anything else
#                          resolves to empty tags)
#   APPS_RELEASE_OUTCOME   step outcome of "Release apps Docker images"
#   BOTS_RELEASE_OUTCOME   step outcome of "Release bots Docker images"
#
# Outputs ($GITHUB_OUTPUT): apps_tag / bots_tag — empty when that group was
# not released this run (the deploy then falls back to :latest via the
# compose file's ${VAR:-latest} defaults).
set -euo pipefail

: "${VERSION_SCHEME:?VERSION_SCHEME is required}"
: "${APPS_RELEASE_OUTCOME:?APPS_RELEASE_OUTCOME is required}"
: "${BOTS_RELEASE_OUTCOME:?BOTS_RELEASE_OUTCOME is required}"

# shellcheck source=scripts/ci/lib/image-repos.sh
source "$(dirname "$0")/lib/image-repos.sh"

# Production scheme: YYMM.DD.<short sha>. Anchored so :latest and dev tags
# never match.
TAG_RE='^[0-9]{4}\.[0-9]{2}\.[0-9a-f]{6,12}$'

# Prints the group's tag on stdout (empty = group not released). Fails loud
# when a released group's local images carry no/ambiguous/mismatched
# production tags, or when the tag cannot be made to exist in GHCR — a deploy
# pinned to a missing tag would fail far later, on the Swarm host.
resolve_group() {
  local group="$1" outcome="$2"
  shift 2
  local repos=("$@")

  if [[ "$outcome" != "success" ]]; then
    echo "resolve-image-tags: $group not released this run (outcome: $outcome)" >&2
    echo ""
    return 0
  fi

  local tag="" repo candidates
  for repo in "${repos[@]}"; do
    candidates=$(docker image ls --format '{{.Tag}}' "$GHCR_NAMESPACE/$repo" | grep -E "$TAG_RE" || true)
    if [[ -z "$candidates" ]]; then
      echo "::error::resolve-image-tags: $group released but $GHCR_NAMESPACE/$repo has no local production tag matching $TAG_RE" >&2
      return 1
    fi
    if [[ "$(echo "$candidates" | wc -l)" -ne 1 ]]; then
      echo "::error::resolve-image-tags: $GHCR_NAMESPACE/$repo has multiple production tags locally: $(echo "$candidates" | tr '\n' ' ')" >&2
      return 1
    fi
    if [[ -z "$tag" ]]; then
      tag="$candidates"
    elif [[ "$tag" != "$candidates" ]]; then
      echo "::error::resolve-image-tags: $group repos disagree on the tag ($tag vs $candidates on $repo)" >&2
      return 1
    fi
  done

  # The tag must be pullable at deploy time. nx release normally pushed it
  # already; if it skipped publishing (the first-run fallback the
  # ensure-bot-images step exists for), push the local image now.
  for repo in "${repos[@]}"; do
    local ref="$GHCR_NAMESPACE/$repo:$tag"
    if ! docker manifest inspect "$ref" > /dev/null 2>&1; then
      echo "resolve-image-tags: $ref not in GHCR yet — pushing" >&2
      docker push "$ref" >&2
      if ! docker manifest inspect "$ref" > /dev/null 2>&1; then
        echo "::error::resolve-image-tags: $ref still missing from GHCR after push" >&2
        return 1
      fi
    fi
  done

  echo "resolve-image-tags: $group => $tag" >&2
  echo "$tag"
}

apps_tag=""
bots_tag=""
if [[ "$VERSION_SCHEME" = "production" ]]; then
  apps_tag=$(resolve_group apps "$APPS_RELEASE_OUTCOME" "${APPS_IMAGE_REPOS[@]}")
  bots_tag=$(resolve_group bots "$BOTS_RELEASE_OUTCOME" "${BOTS_IMAGE_REPOS[@]}")
else
  echo "resolve-image-tags: scheme is '$VERSION_SCHEME' (not production) — deploys are disabled off-master, skipping tag resolution"
fi

{
  echo "apps_tag=$apps_tag"
  echo "bots_tag=$bots_tag"
} >> "$GITHUB_OUTPUT"
echo "resolve-image-tags => apps: '${apps_tag:-<none>}', bots: '${bots_tag:-<none>}'"
