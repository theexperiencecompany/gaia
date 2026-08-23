#!/usr/bin/env bash
# Promotes gate-passed images to :latest for the repos the Swarm deploy does
# not own: gaia-web (a self-host package publish, never deployed by us) and
# gaia-grafana when no backend deploy runs to retag it. Registry-side manifest
# aliasing only (`docker buildx imagetools create`) — no layers move.
#
# Backend repos are deliberately absent: their :latest is re-pointed
# exclusively by retag-latest-alias.sh after a successful deploy/rollback
# convergence, preserving the ":latest == deployed" invariant.
#
# Inputs (env): WEB_IMAGE_TAG / GRAFANA_IMAGE_TAG — the immutable tag pushed
# by this run's build phase; empty means that image wasn't built this run.
set -euo pipefail

# shellcheck source=scripts/ci/lib/image-repos.sh
source "$(dirname "$0")/lib/image-repos.sh"

promoted=false

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
  echo "No image tags to promote (neither web nor grafana was built this run)."
fi
