#!/usr/bin/env bash
# deploy.sh — shipping the built images to production and saying so.
#
# Subcommands:
#   plan                        Compute build.yml's deployment plan: should the
#                               backend prod deploy run, and were backend images
#                               published to GHCR without it (drift). Writes
#                               backend_deploy / backend_orphaned to
#                               $GITHUB_OUTPUT.
#   stack                       `docker stack deploy` the production Swarm stack
#                               from the private gaia-infra checkout at .infra/.
#   verify                      Everything a deploy needs, without touching a
#                               single service — the rehearsal to run after
#                               changing the infra repo, the deploy key or
#                               the tailnet path.
#   retag from-env|rolled-back  Re-point the :latest tags in GHCR at what
#                               production actually runs, so ":latest ==
#                               deployed" holds as an invariant.
#   notify                      Send one deploy-pipeline Discord embed.
#
# Env contract:
#   plan    REF, EVENT_NAME, DOCKER_RELEASE_RESULT (required); API_AFFECTED,
#           BOTS_AFFECTED, GITHUB_OUTPUT.
#   stack   GAIA_IMAGE_TAG / GAIA_BOTS_IMAGE_TAG / GAIA_GRAFANA_IMAGE_TAG pin
#           the images; empty falls through to the compose file's
#           ${VAR:-latest} defaults. Needs the `prod` docker context.
#   verify  as `stack`, minus the write.
#   retag   from-env: APPS_IMAGE_TAG / BOTS_IMAGE_TAG / GRAFANA_IMAGE_TAG.
#           rolled-back: ROLLBACK_MODE, IMAGE_DIGEST, DOCKER_CONTEXT, STACK.
#           Both need a GHCR login with packages:write.
#   notify  DISCORD_WEBHOOK, MESSAGE, COLOR (required); USERNAME.
set -euo pipefail

# shellcheck source=scripts/ci/lib/log.sh
source "$(dirname "$0")/lib/log.sh"
# shellcheck source=scripts/ci/lib/image-repos.sh
source "$(dirname "$0")/lib/image-repos.sh"

cmd_plan() {

  : "${REF:?REF is required}"
  : "${EVENT_NAME:?EVENT_NAME is required}"
  : "${API_AFFECTED:=false}"
  : "${BOTS_AFFECTED:=false}"
  # Job .result values: success | failure | cancelled | skipped. A 'skipped'
  # lane means "not affected", never a failure.
  : "${DOCKER_RELEASE_RESULT:?DOCKER_RELEASE_RESULT is required}"
  # Set by docker-release right after its push steps, independent of later
  # steps in that job (e.g. Discord command sync) that can fail afterwards and
  # flip the job's overall result to 'failure' even though images already
  # landed in GHCR. Empty/anything other than 'true' is treated as "no proof
  # of publish" -- never claim a publish happened without evidence.
  : "${BACKEND_IMAGES_PUBLISHED:=false}"
  : "${MANUAL_MODE_INPUT:=}"
  : "${MANUAL_MODE_EVENT:=}"
  # quality-gate result from the caller (phase=deploy). 'success' default keeps
  # the legacy manual/dispatch flow gate-free. A failed gate must never deploy.
  : "${GATE_RESULT:=success}"

  backend_affected=false
  [[ "$API_AFFECTED" = "true" ]] || [[ "$BOTS_AFFECTED" = "true" ]] && backend_affected=true

  backend_deploy=false
  # An explicit operator mode that deliberately skips the deploy is NOT drift —
  # flagging it as an orphan turns every routine `deployment_mode=none` run into
  # a false alarm.
  deliberate_backend_skip=false

  manual_mode="${MANUAL_MODE_INPUT:-}"
  if [[ -z "$manual_mode" ]]; then
    manual_mode="${MANUAL_MODE_EVENT:-}"
  fi
  if [[ -z "$manual_mode" ]]; then
    manual_mode="auto"
  fi

  on_master=false
  [[ "$REF" = "refs/heads/master" ]] && on_master=true

  gate_passed=false
  [[ "$GATE_RESULT" = "success" ]] && gate_passed=true

  if [[ "$on_master" = "false" ]]; then
    echo "Not on master; deploy jobs disabled."
  elif [[ "$EVENT_NAME" = "workflow_dispatch" ]]; then
    case "$manual_mode" in
      auto)
        if [[ "$gate_passed" = "true" ]] && [[ "$backend_affected" = "true" ]] && [[ "$DOCKER_RELEASE_RESULT" = "success" ]]; then
          backend_deploy=true
        fi
        ;;
      # Explicit operator override bypasses affected-detection AND lane-result
      # gating -- this is the documented self-heal remedy for drift:
      # `deployment_mode=deploy` redeploys whatever is currently tagged :latest
      # in GHCR, regardless of what this run's build lane decided.
      deploy)
        backend_deploy=true
        ;;
      none)
        deliberate_backend_skip=true
        ;;
      *)
        echo "::error::Invalid deployment_mode '$manual_mode'. Use auto, deploy, or none."
        exit 1
        ;;
    esac
  else
    # Automatic push-triggered plan (main.yml phase=deploy passes GATE_RESULT).
    if [[ "$gate_passed" = "true" ]] && [[ "$backend_affected" = "true" ]] && [[ "$DOCKER_RELEASE_RESULT" = "success" ]]; then
      backend_deploy=true
    fi
  fi

  # Orphan detection: immutable images landed in GHCR but the deploy that
  # would roll them out did not run this time, for ANY reason (lane failure,
  # cancellation, a failed quality gate, or the plan deciding not to deploy).
  # :latest does not move in that case (it is re-pointed only after a
  # successful deploy), so production is unaffected — the drift is master
  # being ahead of what runs. Scoped to master:
  # off-master manual builds intentionally never deploy and must not be
  # reported as drift. A deploy the operator explicitly excluded via a manual
  # mode is not drift either.
  backend_orphaned=false
  if [[ "$on_master" = "true" ]]; then
    if [[ "$BACKEND_IMAGES_PUBLISHED" = "true" ]] && [[ "$backend_deploy" != "true" ]] && [[ "$deliberate_backend_skip" != "true" ]]; then
      backend_orphaned=true
    fi
  fi

  {
    echo "backend_deploy=$backend_deploy"
    echo "backend_orphaned=$backend_orphaned"
    echo "docker_release_result=$DOCKER_RELEASE_RESULT"
  } >> "$GITHUB_OUTPUT"

  echo "Deploy plan => backend: $backend_deploy"
  echo "Orphan check => backend_orphaned: $backend_orphaned"
  echo "  docker-release result: $DOCKER_RELEASE_RESULT (images_published=$BACKEND_IMAGES_PUBLISHED)"
}

_cmd_swarm_stack() {

  local MODE="$1"
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
      echo "deploy verify: OK (infra ref $(git -C .infra rev-parse --short HEAD), obs config hash $OBS_CFG_HASH, $(echo "$rendered" | yq '.services | length') services)"
      ;;
    *)
      echo "deploy.sh: unknown stack mode '$MODE' (deploy|verify)" >&2
      exit 2
      ;;
  esac
}

cmd_retag() {

  MODE="${1:?usage: deploy.sh retag from-env|rolled-back}"


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
}

cmd_notify() {

  : "${DISCORD_WEBHOOK:?DISCORD_WEBHOOK is required}"
  : "${MESSAGE:?MESSAGE is required}"
  : "${COLOR:?COLOR is required}"
  USERNAME="${USERNAME:-Gaia Deploy Bot}"

  # Always log the full message first, so the run itself records what was (or
  # failed to be) delivered even when the webhook call is lost.
  echo "Discord notification:"
  printf '%s\n' "$MESSAGE"

  color_int=$((16#${COLOR#\#}))

  # Discord caps embed descriptions at 4096 chars — truncate instead of 400ing.
  message="$MESSAGE"
  if [[ "${#message}" -gt 4000 ]]; then
    message="${message:0:4000}"$'\n'"…(truncated)"
  fi

  payload=$(jq -n --arg u "$USERNAME" --arg d "$message" --argjson c "$color_int" \
    '{username: $u, embeds: [{description: $d, color: $c}]}')

  response_file=$(mktemp)
  trap 'rm -f "$response_file"' EXIT

  # Bounded: a stuck DNS lookup or socket must not hold a deploy workflow
  # hostage for a notification that is non-blocking by design.
  status=$(curl -sS --connect-timeout 5 --max-time 20 -o "$response_file" -w '%{http_code}' \
    -H 'Content-Type: application/json' -d "$payload" "$DISCORD_WEBHOOK")

  if [[ "$status" -lt 200 || "$status" -ge 300 ]]; then
    echo "::error::Discord webhook returned HTTP $status: $(cat "$response_file")"
    exit 1
  fi
  ci_ok "deploy notify: OK (HTTP $status)"
}

usage() {
  sed -n '2,20p' "$0" >&2
}

main() {
  local sub="${1:-}"
  shift || true
  case "$sub" in
    plan)   cmd_plan "$@" ;;
    stack)  _cmd_swarm_stack deploy "$@" ;;
    verify) _cmd_swarm_stack verify "$@" ;;
    retag)  cmd_retag "$@" ;;
    notify) cmd_notify "$@" ;;
    *)
      echo "deploy.sh: unknown subcommand '${sub}'" >&2
      usage
      exit 2
      ;;
  esac
}

main "$@"
