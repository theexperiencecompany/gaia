#!/bin/sh
# Inject Docker Swarm secrets as environment variables before exec-ing the process.
# Falls through transparently when no secrets are present (local docker compose dev).
[ -f /run/secrets/gaia_infisical_token ]                          && export INFISICAL_TOKEN=$(cat /run/secrets/gaia_infisical_token)
[ -f /run/secrets/gaia_infisical_machine_identity_client_id ]     && export INFISICAL_MACHINE_IDENTITY_CLIENT_ID=$(cat /run/secrets/gaia_infisical_machine_identity_client_id)
[ -f /run/secrets/gaia_infisical_machine_identity_client_secret ] && export INFISICAL_MACHINE_IDENTITY_CLIENT_SECRET=$(cat /run/secrets/gaia_infisical_machine_identity_client_secret)
[ -f /run/secrets/gaia_infisical_project_id ]                     && export INFISICAL_PROJECT_ID=$(cat /run/secrets/gaia_infisical_project_id)
[ -f /run/secrets/gaia_metrics_token ]                            && export METRICS_TOKEN=$(cat /run/secrets/gaia_metrics_token)
exec "$@"
