#!/usr/bin/env bash
# Renders or deploys the production Swarm stack from the private gaia-infra
# checkout at .infra/.
#
# Modes:
#   deploy   `docker stack deploy` against the prod context. Env
#            GAIA_IMAGE_TAG / GAIA_BOTS_IMAGE_TAG / GAIA_GRAFANA_IMAGE_TAG pin
#            the images; empty falls through to the compose file's
#            ${VAR:-latest} defaults.
#   verify   Everything a deploy needs, without touching a single service:
#            the private checkout resolved, the observability configs are
#            present, the compose file renders against the prod context
#            (`docker stack config` validates it and resolves every ${VAR}),
#            and the resulting service list is printed for the run log.
#            This is the rehearsal to run after changing the infra split,
#            the deploy key, or GAIA_INFRA_REF.
#
# Observability configs ship as Swarm configs (stored in the cluster), not
# host bind mounts, so this deploys cleanly via the remote context with no
# files on the VM. Swarm configs are immutable, so their names carry a
# content hash: a changed config file produces a new config object that
# services roll onto. The hash covers all config files.
set -euo pipefail

MODE="${1:?usage: swarm-stack.sh deploy|verify}"
STACK_FILE=".infra/docker/docker-compose.prod.yml"
OBS_DIR=".infra/docker/observability"

OBS_CFG_HASH=$(cat \
  "$OBS_DIR/prometheus.yml" \
  "$OBS_DIR/loki-config.yaml" \
  "$OBS_DIR/promtail-config.yaml" \
  "$OBS_DIR/blackbox.yml" \
  "$OBS_DIR/rabbitmq-enabled-plugins" \
  | sha256sum | cut -c1-12)
export OBS_CFG_HASH

case "$MODE" in
  deploy)
    docker --context prod stack deploy \
      --with-registry-auth \
      -c "$STACK_FILE" \
      gaia-prod
    ;;
  verify)
    rendered=$(docker --context prod stack config -c "$STACK_FILE")
    echo "::group::Rendered stack (services and images)"
    echo "$rendered" | yq '.services | map_values(.image)'
    echo "::endgroup::"
    echo "swarm-stack verify: OK (infra ref $(git -C .infra rev-parse --short HEAD), obs config hash $OBS_CFG_HASH, $(echo "$rendered" | yq '.services | length') services)"
    ;;
  *)
    echo "swarm-stack.sh: unknown mode '$MODE' (deploy|verify)" >&2
    exit 2
    ;;
esac
