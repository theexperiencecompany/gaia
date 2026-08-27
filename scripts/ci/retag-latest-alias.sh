#!/usr/bin/env bash
# Re-points the :latest tags in GHCR at what production actually runs, so
# ":latest == deployed" holds as an invariant. `docker buildx imagetools
# create` is a pure registry-side manifest operation — no layers are pulled
# or pushed. Requires a GHCR login with packages:write.
#
# Modes:
#   from-env      after a successful deploy convergence. Reads the tags the
#                 stack was deployed with (env: APPS_IMAGE_TAG /
#                 BOTS_IMAGE_TAG / GRAFANA_IMAGE_TAG, empty = that group was
#                 deployed from :latest, already the alias — nothing to do).
#   rolled-back   after a successful rollback convergence. Re-points :latest
#                 at the images the rolled-back services now run, resolved
#                 from the live service specs (env: ROLLBACK_MODE,
#                 IMAGE_DIGEST, DOCKER_CONTEXT, STACK) — without this, a
#                 rollback would leave :latest naming the bad build, and the
#                 next tag-less `docker stack deploy` would resolve it again.
set -euo pipefail

MODE="${1:?usage: retag-latest-alias.sh from-env|rolled-back}"

# shellcheck source=scripts/ci/lib/image-repos.sh
source "$(dirname "$0")/lib/image-repos.sh"

# repo_of ghcr.io/org/name:tag[@digest] -> ghcr.io/org/name
repo_of() {
  local ref="${1%%@*}"
  local base="${ref##*/}"
  if [[ "$base" == *:* ]]; then
    echo "${ref%:*}"
  else
    echo "$ref"
  fi
}

retag() {
  local ref="$1" repo
  repo=$(repo_of "$ref")
  echo "Pointing $repo:latest -> $ref"
  docker buildx imagetools create -t "$repo:latest" "$ref"
}

case "$MODE" in
  from-env)
    retagged=false
    if [[ -n "${APPS_IMAGE_TAG:-}" ]]; then
      for repo in "${APPS_IMAGE_REPOS[@]}"; do
        retag "$GHCR_NAMESPACE/$repo:$APPS_IMAGE_TAG"
      done
      retagged=true
    fi
    if [[ -n "${BOTS_IMAGE_TAG:-}" ]]; then
      for repo in "${BOTS_IMAGE_REPOS[@]}"; do
        retag "$GHCR_NAMESPACE/$repo:$BOTS_IMAGE_TAG"
      done
      retagged=true
    fi
    if [[ -n "${GRAFANA_IMAGE_TAG:-}" ]]; then
      retag "$GHCR_NAMESPACE/$GRAFANA_IMAGE_REPO:$GRAFANA_IMAGE_TAG"
      retagged=true
    fi
    if [[ "$retagged" = "false" ]]; then
      echo "No concrete tags were passed — stack was deployed from :latest, alias already correct."
    fi
    ;;

  rolled-back)
    # No defaults: the caller owns the context/stack names (they are the same
    # literals the rollback job's own docker commands use). A silent default
    # here could target a different cluster than the rollback just touched.
    : "${ROLLBACK_MODE:?ROLLBACK_MODE is required}"
    : "${DOCKER_CONTEXT:?DOCKER_CONTEXT is required}"
    : "${STACK:?STACK is required}"
    if [[ "$ROLLBACK_MODE" = "digest" ]]; then
      # Digest rollback only touches gaia-backend/arq_worker, both on the gaia
      # repo — re-point exactly that repo's :latest at the pinned ref.
      : "${IMAGE_DIGEST:?IMAGE_DIGEST is required for digest mode}"
      retag "$IMAGE_DIGEST"
    else
      # `service rollback` restored each service's previous spec; read the
      # image (repo:tag@digest) each rolled-back service now runs and
      # re-point that repo's :latest at it. Deduped: gaia-backend and
      # arq_worker share the gaia repo.
      refs=$(for svc in $(docker --context "$DOCKER_CONTEXT" stack services "$STACK" --format '{{.Name}}' \
          | grep -E 'gaia-backend|arq_worker|voice-agent-worker|discord-bot|slack-bot|telegram-bot|whatsapp-bot|imessage-bot'); do
          docker --context "$DOCKER_CONTEXT" service inspect "$svc" \
            --format '{{.Spec.TaskTemplate.ContainerSpec.Image}}'
        done | sort -u)
      if [[ -z "$refs" ]]; then
        echo "::error::rolled-back retag: no matching services found in stack $STACK"
        exit 1
      fi
      while IFS= read -r ref; do
        retag "$ref"
      done <<< "$refs"
    fi
    ;;

  *)
    echo "::error::retag-latest-alias: unknown mode '$MODE' (use from-env or rolled-back)"
    exit 1
    ;;
esac
