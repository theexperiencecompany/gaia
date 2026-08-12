#!/usr/bin/env bash
# Computes build.yml's deployment plan: which production deploy workflows
# should run, and whether any image lane published to GHCR without a
# corresponding deploy running (a "publish without deploy" drift risk).
#
# Consumed by the `deployment-plan` job, which runs with `if: always()` so a
# failed/cancelled lane (docker-release, docker-web, docker-grafana) never
# skips planning outright -- each lane's result is evaluated explicitly here
# instead of relying on implicit all-success gating.
#
# Coupling rule: a push that touches ONLY backend or ONLY web deploys that
# side independently -- a failed docker-web must never block a ready backend
# deploy, and vice versa (the original incident this fixes). But a push that
# touches BOTH backend and web is a single coupled unit: if either lane
# failed, deploy NEITHER, rather than shipping (say) a new frontend against
# a still-old backend it wasn't built against. The old implicit
# all-or-nothing gate accidentally provided this protection for coupled
# pushes -- this preserves that property while still fixing the
# single-side-failure incident.
#
# Writes backend_deploy / frontend_deploy / backend_orphaned /
# frontend_orphaned to $GITHUB_OUTPUT. trigger-deploy and trigger-web consume
# only backend_deploy / frontend_deploy -- keep those two names and their
# 'true'/'false' string contract stable.
set -euo pipefail

: "${REF:?REF is required}"
: "${EVENT_NAME:?EVENT_NAME is required}"
: "${API_AFFECTED:=false}"
: "${BOTS_AFFECTED:=false}"
: "${WEB_AFFECTED:=false}"
# Job .result values: success | failure | cancelled | skipped. A 'skipped'
# lane means "not affected", never a failure -- it must not trigger the
# coupling hold below.
: "${DOCKER_RELEASE_RESULT:?DOCKER_RELEASE_RESULT is required}"
: "${DOCKER_WEB_RESULT:?DOCKER_WEB_RESULT is required}"
# Set by docker-release right after its push steps, independent of later
# steps in that job (e.g. Discord command sync) that can fail afterwards and
# flip the job's overall result to 'failure' even though images already
# landed in GHCR. Empty/anything other than 'true' is treated as "no proof
# of publish" -- never claim a publish happened without evidence.
: "${BACKEND_IMAGES_PUBLISHED:=false}"
: "${MANUAL_MODE_INPUT:=}"
: "${MANUAL_MODE_EVENT:=}"

release_failed=false
[[ "$DOCKER_RELEASE_RESULT" = "failure" ]] || [[ "$DOCKER_RELEASE_RESULT" = "cancelled" ]] && release_failed=true
web_failed=false
[[ "$DOCKER_WEB_RESULT" = "failure" ]] || [[ "$DOCKER_WEB_RESULT" = "cancelled" ]] && web_failed=true

backend_affected=false
[[ "$API_AFFECTED" = "true" ]] || [[ "$BOTS_AFFECTED" = "true" ]] && backend_affected=true

both_touched=false
[[ "$backend_affected" = "true" ]] && [[ "$WEB_AFFECTED" = "true" ]] && both_touched=true

backend_deploy=false
frontend_deploy=false
coupled_hold=false
# Explicit operator modes deliberately skip a side. A side the operator chose
# not to deploy is NOT drift — flagging it as an orphan turns every routine
# `deployment_mode=backend-only` run into a false alarm (which is exactly what
# happened: both backend-only dispatches on 2026-08-10 fired the orphan alert
# for the deliberately-skipped frontend).
deliberate_backend_skip=false
deliberate_frontend_skip=false

# Shared by the automatic push plan and workflow_dispatch's `auto` mode --
# both derive the plan from affected-detection + lane results the same way.
compute_auto_plan() {
  if [[ "$both_touched" = "true" ]]; then
    if [[ "$release_failed" = "true" ]] || [[ "$web_failed" = "true" ]]; then
      # Coupled push, one side red: hold both back rather than deploy a
      # frontend/backend pair that was never actually tested together.
      coupled_hold=true
    elif [[ "$DOCKER_RELEASE_RESULT" = "success" ]] && [[ "$DOCKER_WEB_RESULT" = "success" ]]; then
      backend_deploy=true
      frontend_deploy=true
    fi
    # Neither failed nor both-succeeded (e.g. a hypothetical 'skipped' on an
    # affected lane) -- no verified success on both sides, so don't deploy,
    # but this isn't a failure either, so don't badge it as a coupled hold.
  else
    if [[ "$backend_affected" = "true" ]] && [[ "$DOCKER_RELEASE_RESULT" = "success" ]]; then
      backend_deploy=true
    fi
    # Single-side push: frontend syncs from source, not docker-web's image,
    # and isn't coupled to a backend change this time -- keep it decoupled
    # from docker-web's result, same as before this change.
    frontend_deploy=true
  fi
}

manual_mode="${MANUAL_MODE_INPUT:-}"
if [[ -z "$manual_mode" ]]; then
  manual_mode="${MANUAL_MODE_EVENT:-}"
fi
if [[ -z "$manual_mode" ]]; then
  manual_mode="auto"
fi

on_master=false
[[ "$REF" = "refs/heads/master" ]] && on_master=true

if [[ "$on_master" = "false" ]]; then
  echo "Not on master; deploy jobs disabled."
elif [[ "$EVENT_NAME" = "workflow_dispatch" ]]; then
  case "$manual_mode" in
    auto)
      compute_auto_plan
      ;;
    # Explicit operator overrides bypass affected-detection, lane-result
    # gating, AND the coupling rule -- this is the documented self-heal
    # remedy for drift: `deployment_mode=both` (or backend-only /
    # frontend-only) redeploys whatever is currently tagged :latest in
    # GHCR, regardless of what this run's build lanes decided.
    backend-only)
      backend_deploy=true
      deliberate_frontend_skip=true
      ;;
    frontend-only)
      frontend_deploy=true
      deliberate_backend_skip=true
      ;;
    both)
      backend_deploy=true
      frontend_deploy=true
      ;;
    none)
      deliberate_backend_skip=true
      deliberate_frontend_skip=true
      ;;
    *)
      echo "::error::Invalid deployment_mode '$manual_mode'. Use auto, backend-only, frontend-only, both, or none."
      exit 1
      ;;
  esac
else
  # Automatic push-triggered plan.
  compute_auto_plan
fi

# Orphan detection: images landed in GHCR tagged :latest but the deploy that
# would roll them out did not run this time, for ANY reason (lane failure,
# cancellation, the plan deciding not to deploy, or a coupling hold).
# Scoped to master: off-master manual builds intentionally never deploy and
# must not be reported as drift. A side the operator explicitly excluded via
# a manual mode is not drift either.
#
# The frontend check needs BOTH web-affected and lane success: docker-web
# succeeds even when web isn't affected (it just skips the build/push), so
# the job result alone is not publish evidence -- it once claimed "gaia-web
# was published" on a run that never built a web image.
backend_orphaned=false
frontend_orphaned=false
if [[ "$on_master" = "true" ]]; then
  if [[ "$BACKEND_IMAGES_PUBLISHED" = "true" ]] && [[ "$backend_deploy" != "true" ]] && [[ "$deliberate_backend_skip" != "true" ]]; then
    backend_orphaned=true
  fi
  if [[ "$WEB_AFFECTED" = "true" ]] && [[ "$DOCKER_WEB_RESULT" = "success" ]] && [[ "$frontend_deploy" != "true" ]] && [[ "$deliberate_frontend_skip" != "true" ]]; then
    frontend_orphaned=true
  fi
  # A coupling hold strands BOTH sides together even when only one lane
  # actually failed -- e.g. web failed, backend published fine but is held
  # back anyway. Flag both explicitly so the healthy side isn't missed.
  # (Coupling holds only occur in auto plans, never in the explicit manual
  # modes, so the deliberate-skip suppression can't apply here.)
  if [[ "$coupled_hold" = "true" ]]; then
    backend_orphaned=true
    frontend_orphaned=true
  fi
fi

{
  echo "backend_deploy=$backend_deploy"
  echo "frontend_deploy=$frontend_deploy"
  echo "backend_orphaned=$backend_orphaned"
  echo "frontend_orphaned=$frontend_orphaned"
  echo "coupled_hold=$coupled_hold"
  echo "docker_release_result=$DOCKER_RELEASE_RESULT"
  echo "docker_web_result=$DOCKER_WEB_RESULT"
} >> "$GITHUB_OUTPUT"

echo "Deploy plan => backend: $backend_deploy, frontend: $frontend_deploy, coupled_hold: $coupled_hold"
echo "Orphan check => backend_orphaned: $backend_orphaned, frontend_orphaned: $frontend_orphaned"
echo "  both_touched: $both_touched, docker-release result: $DOCKER_RELEASE_RESULT (images_published=$BACKEND_IMAGES_PUBLISHED), docker-web result: $DOCKER_WEB_RESULT"
