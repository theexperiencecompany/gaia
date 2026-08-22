#!/usr/bin/env bash
# Computes build.yml's deployment plan: whether the backend production deploy
# should run, and whether backend images were published to GHCR without that
# deploy running (a "publish without deploy" drift risk).
#
# Backend only. The frontend deploys itself: Cloudflare Workers Builds watches
# the repository and builds/deploys the web app on every master push,
# independently of CI. CI's role for the frontend ends at publishing the
# gaia-web image (docker-web) for self-host users, which is a package publish,
# not a deploy — so no frontend deploy is planned, and no backend/frontend
# coupling exists to enforce.
#
# Consumed by the `deployment-plan` job, which runs with `if: always()` so a
# failed/cancelled docker-release lane never skips planning outright — the
# lane's result is evaluated explicitly here instead of relying on implicit
# all-success gating.
#
# Writes backend_deploy / backend_orphaned to $GITHUB_OUTPUT. trigger-deploy
# consumes only backend_deploy — keep its name and 'true'/'false' string
# contract stable.
set -euo pipefail

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
