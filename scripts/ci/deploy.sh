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
#   migrate                     Before the rollout, run the release's data
#                               migrations (apps/api/scripts/post_deploy.py) as
#                               a one-shot Swarm job on the NEW apps image; a
#                               failure stops the deploy with nothing touched.
#                               Then run one asking whether any
#                               conversation still needs the migration catch-up.
#                               None: return, and the rollout runs with no
#                               downtime. Some: scale the old writers to 0, run
#                               the catch-up job, and on its failure scale them
#                               back up and fail. Writes catch_up= and
#                               writers_down= to $GITHUB_OUTPUT.
#   verify                      Everything a deploy needs, without touching a
#                               single service — the rehearsal to run after
#                               changing the infra repo, the deploy key or
#                               the tailnet path.
#   smoke                       Read production as an anonymous visitor (the
#                               public pages and API reads in
#                               lib/prod-smoke-targets.toml, then a polite burst
#                               against the anonymous rate limit) and write
#                               verdict=pass|warn|fail|error and summary=. Fails
#                               on fail or error. It never changes production:
#                               a failure alerts, and rolling back is a person's
#                               call (action=rollback).
#   retag from-env|rolled-back  Re-point the :latest tags in GHCR at what
#                               production actually runs, so ":latest ==
#                               deployed" holds as an invariant.
#   notify                      Send one deploy-pipeline message to Discord and
#                               Slack (the channel Grafana alerts post to), from
#                               a fixed template per STATE.
#   failing-checks <sha>        The check-runs that failed on <sha>, as the cause
#                               lines a blocked message renders.
#   served-commit               Record the commit prod's /health serves before
#                               a deploy (previous=, scopes the change list).
#   verify-commit               Fail unless prod's /health (and each bot's,
#                               when bots were deployed) serves the commit
#                               baked into the deployed image. Writes commit=.
#   verify-alert-rules          Fail unless the rules file in the running
#                               grafana task carries exactly the uids in the
#                               repo's alert-rules.yaml.
#   changelog                   Commit subjects PREVIOUS..COMMIT (changes=).
#   unwedge                     Force-cancel master runs parked on a deployment
#                               gate nobody can release (no reviewers, no wait
#                               timer) past STUCK_LIMIT_SECS, waiting out any
#                               such gate still inside the limit. Such a run holds
#                               build.yml's master concurrency group, so every
#                               later push's deploy queues behind it forever.
#
# Env contract:
#   plan    REF, EVENT_NAME, DOCKER_RELEASE_RESULT (required); API_AFFECTED,
#           BOTS_AFFECTED, GITHUB_OUTPUT.
#   stack   GAIA_IMAGE_TAG / GAIA_BOTS_IMAGE_TAG / GAIA_GRAFANA_IMAGE_TAG pin
#           the images; empty falls through to the compose file's
#           ${VAR:-latest} defaults. Needs the `prod` docker context.
#   verify  as `stack`, minus the write.
#   smoke   PROD_ORIGIN, PROD_WEB_ORIGIN; GITHUB_OUTPUT, GITHUB_STEP_SUMMARY.
#           No secrets: every read is anonymous.
#   migrate GITHUB_OUTPUT (required); GAIA_IMAGE_TAG as `stack`;
#           MIGRATE_RELEASE_TIMEOUT_SECS, MIGRATE_CHECK_TIMEOUT_SECS,
#           MIGRATE_CATCH_UP_TIMEOUT_SECS, MIGRATE_WRITERS_TIMEOUT_SECS,
#           MIGRATE_POLL_SECS. Needs the `prod` docker context and a GHCR
#           login (the job pulls the image).
#   retag   from-env: APPS_IMAGE_TAG / BOTS_IMAGE_TAG / GRAFANA_IMAGE_TAG.
#           rolled-back: ROLLBACK_MODE, IMAGE_DIGEST, DOCKER_CONTEXT, STACK;
#           re-points every service on one of our repos, grafana included.
#           Both need a GHCR login with packages:write.
#   notify  STATE (deploy_blocked | deploy_failed | deploy_succeeded |
#           recovered) with IMPACT, CAUSE, ACTION, and CLEARS_WHEN for the two
#           failure states — one template per state, never free prose. SUBJECT
#           tails the headline, RUN_LINK overrides the run URL, DRY_RUN renders
#           and length-guards without delivering. The legacy MESSAGE + COLOR
#           pair is still honored for callers that predate STATE.
#           DISCORD_WEBHOOK, SLACK_WEBHOOK (each attempted; a missing or failed
#           one fails the step); USERNAME.
#   failing-checks  <sha> [max]  GITHUB_REPOSITORY; GH_TOKEN or GITHUB_TOKEN.
#   served-commit  PROD_ORIGIN, GITHUB_OUTPUT.
#   verify-commit  PROD_ORIGIN, GITHUB_OUTPUT; APPS_IMAGE_TAG (empty = latest),
#           BOTS_IMAGE_TAG, VERIFY_TIMEOUT_SECS, VERIFY_CONSECUTIVE,
#           VERIFY_POLL_SECS. Needs a GHCR login.
#   verify-alert-rules  ALERT_RULES_FILE, GRAFANA_VERIFY_TIMEOUT_SECS,
#           GRAFANA_VERIFY_POLL_SECS. Needs the `prod` docker context.
#   changelog  COMMIT, GITHUB_REPOSITORY, GITHUB_OUTPUT; PREVIOUS. Needs GH_TOKEN.
#   unwedge GITHUB_REPOSITORY, GITHUB_RUN_ID, GITHUB_OUTPUT (required);
#           STUCK_LIMIT_SECS. Needs actions:write. Writes reaped=<run ids>.
set -euo pipefail

# shellcheck source=scripts/ci/lib/log.sh
source "$(dirname "$0")/lib/log.sh"
# shellcheck source=scripts/ci/lib/image-repos.sh
source "$(dirname "$0")/lib/image-repos.sh"
# shellcheck source=scripts/ci/lib/webhook.sh
source "$(dirname "$0")/lib/webhook.sh"

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
    # Automatic push-triggered plan (build.yml phase=deploy, called from ci.yml with the gate's result).
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

# The pre-rollout migrations (cmd_migrate). First the release step
# (apps/api/scripts/post_deploy.py) runs every pending data migration while the
# old build still serves. Then the new API refuses to
# boot while any conversation holds data the conversation log does not match,
# and the old build writes that data until it stops, so a catch-up runs only
# with the old writers down. Bots and the voice agent write conversations
# through the API, so stopping these two stops every conversation write.
_MIGRATE_TEMPLATE="gaia-prod_gaia-backend"
_MIGRATE_WRITERS=(gaia-prod_gaia-backend gaia-prod_arq_worker)
_MIGRATE_SCRIPT=(python -m scripts.migrate_conversations)
_MIGRATE_RELEASE_STEP=(python -m scripts.post_deploy --apply)
# CATCH_UP_NEEDED_EXIT in apps/api/scripts/migrate_conversations.py.
_MIGRATE_CATCH_UP_NEEDED=3
# Job services not yet removed, and the `svc=replicas` pairs that put stopped
# writers back: the EXIT trap reads both, so no exit path leaves either behind.
_MIGRATE_JOBS=""
_MIGRATE_RESTORE=""
_MIGRATE_CAUGHT_UP=false
_MIGRATE_ENV_FILE=""
_MIGRATE_JOB_EXIT=""

_migrate_docker() { docker --context prod "$@"; }

# _migrate_running <service> — its tasks Running right now, whatever their
# desired state: a task told to shut down still writes until it exits.
_migrate_running() {
  local states
  states=$(_migrate_docker service ps "$1" --format '{{.CurrentState}}') \
    || ci_die "deploy migrate: cannot list the tasks of $1"
  grep -c '^Running' <<< "$states" || true
}

# _migrate_await <service> <le|ge> <count> — wait, bounded by
# MIGRATE_WRITERS_TIMEOUT_SECS, until its Running tasks are at most / at least
# count; 1 on timeout.
_migrate_await() {
  local svc="$1" op="$2" want="$3" running
  local deadline=$(( $(date +%s) + ${MIGRATE_WRITERS_TIMEOUT_SECS:-300} ))
  while :; do
    running=$(_migrate_running "$svc") || return 1
    if [[ "$op" = le ]] && (( running <= want )); then return 0; fi
    if [[ "$op" = ge ]] && (( running >= want )); then return 0; fi
    (( $(date +%s) < deadline )) || return 1
    sleep "${MIGRATE_POLL_SECS:-5}"
  done
}

_migrate_job_logs() {
  ci_group "Logs of $1"
  _migrate_docker service logs --raw "$1" 2>&1 || ci_warn "deploy migrate: could not read the logs of $1"
  ci_endgroup
}

_migrate_remove_job() {
  _migrate_docker service rm "$1" > /dev/null \
    || ci_warn "deploy migrate: could not remove the job service $1 — remove it on the VM"
  _MIGRATE_JOBS="${_MIGRATE_JOBS/ $1/}"
}

# _migrate_job <kind> <timeout secs> <command...> — run command as a one-shot
# job on the new image with the backend's secrets, networks, env and working
# directory, and set _MIGRATE_JOB_EXIT to its exit code. Dies when the job never
# ran to an exit (rejected, shut down, or past the timeout).
_migrate_job() {
  local kind="$1" timeout="$2"
  shift 2
  local name template secret network workdir args=()
  name="gaia-migrate-${kind}-${GITHUB_RUN_ID:-local}-$(date +%s)"
  template=$(_migrate_docker service inspect "$_MIGRATE_TEMPLATE" --format '{{json .Spec.TaskTemplate}}') \
    || ci_die "deploy migrate: cannot inspect $_MIGRATE_TEMPLATE, whose secrets, networks and env the job copies"

  # The env goes through a 0600 file, never argv or the log.
  _MIGRATE_ENV_FILE=$(mktemp)
  chmod 600 "$_MIGRATE_ENV_FILE"
  jq -r '.ContainerSpec.Env // [] | .[]' <<< "$template" > "$_MIGRATE_ENV_FILE"
  args+=(--env-file "$_MIGRATE_ENV_FILE")
  while IFS= read -r secret; do
    [[ -z "$secret" ]] || args+=(--secret "$secret")
  done < <(jq -r '.ContainerSpec.Secrets // [] | .[] | "source=\(.SecretName),target=\(.File.Name)"' <<< "$template")
  while IFS= read -r network; do
    [[ -z "$network" ]] || args+=(--network "$network")
  done < <(jq -r '.Networks // [] | .[].Target' <<< "$template")
  workdir=$(jq -r '.ContainerSpec.Dir // empty' <<< "$template")
  [[ -z "$workdir" ]] || args+=(--workdir "$workdir")

  echo "deploy migrate: starting the $kind job $name on $_MIGRATE_IMAGE: $*"
  _MIGRATE_JOBS="$_MIGRATE_JOBS $name"
  _migrate_docker service create --detach --quiet --with-registry-auth \
    --name "$name" --label "gaia.migrate=$kind" \
    --mode replicated-job --restart-condition none \
    "${args[@]}" "$_MIGRATE_IMAGE" "$@" > /dev/null \
    || ci_die "deploy migrate: could not create the $kind job $name"
  rm -f "$_MIGRATE_ENV_FILE"
  _MIGRATE_ENV_FILE=""

  local deadline=$(( $(date +%s) + timeout )) task status="{}" state code
  while :; do
    task=$(_migrate_docker service ps "$name" --quiet --no-trunc | head -n 1) \
      || ci_die "deploy migrate: cannot list the task of the $kind job $name"
    state=""
    if [[ -n "$task" ]]; then
      status=$(_migrate_docker inspect "$task" --format '{{json .Status}}') \
        || ci_die "deploy migrate: cannot inspect task $task of the $kind job $name"
      state=$(jq -r '.State' <<< "$status")
    fi
    case "$state" in
      complete | failed) break ;;
      rejected | shutdown | orphaned | remove)
        _migrate_job_logs "$name"
        ci_die "deploy migrate: the $kind job $name never ran to an exit (task $state: $(jq -r '.Err // "no error given"' <<< "$status"))"
        ;;
    esac
    if (( $(date +%s) >= deadline )); then
      _migrate_job_logs "$name"
      ci_die "deploy migrate: the $kind job $name did not finish within ${timeout}s (task ${state:-not scheduled yet})"
    fi
    sleep "${MIGRATE_POLL_SECS:-5}"
  done

  _migrate_job_logs "$name"
  code=$(jq -r '.ContainerStatus.ExitCode // empty' <<< "$status")
  [[ -n "$code" ]] || ci_die "deploy migrate: the $kind job $name ended $state with no exit code"
  _migrate_remove_job "$name"
  _MIGRATE_JOB_EXIT="$code"
  echo "deploy migrate: the $kind job exited $code"
}

# On every exit: no job service outlives the step, and writers stopped for a
# catch-up that did not succeed come back on the image they were running.
_migrate_on_exit() {
  local rc=$? job pair
  [[ -z "$_MIGRATE_ENV_FILE" ]] || rm -f "$_MIGRATE_ENV_FILE"
  for job in $_MIGRATE_JOBS; do
    _migrate_remove_job "$job"
  done
  if [[ -n "$_MIGRATE_RESTORE" ]] && [[ "$_MIGRATE_CAUGHT_UP" != true ]]; then
    echo "deploy migrate: scaling the old writers back up ($_MIGRATE_RESTORE)"
    # shellcheck disable=SC2086 # one svc=replicas word per writer
    if _migrate_docker service scale --detach $_MIGRATE_RESTORE > /dev/null; then
      for pair in $_MIGRATE_RESTORE; do
        _migrate_await "${pair%%=*}" ge "${pair#*=}" \
          || printf '::error::%s\n' "deploy migrate: ${pair%%=*} is not back to ${pair#*=} Running tasks — check the VM" >&2
      done
    else
      printf '::error::%s\n' "deploy migrate: could not scale the old writers back up — prod is DOWN; run docker service scale $_MIGRATE_RESTORE" >&2
    fi
    (( rc != 0 )) || rc=1
  fi
  exit "$rc"
}

cmd_migrate() {
  : "${GITHUB_OUTPUT:?GITHUB_OUTPUT is required}"
  _MIGRATE_IMAGE="$GHCR_NAMESPACE/${APPS_IMAGE_REPOS[0]}:${GAIA_IMAGE_TAG:-latest}"
  trap _migrate_on_exit EXIT

  _migrate_job release "${MIGRATE_RELEASE_TIMEOUT_SECS:-1800}" "${_MIGRATE_RELEASE_STEP[@]}"
  [[ "$_MIGRATE_JOB_EXIT" = 0 ]] \
    || ci_die "deploy migrate: the release's migrations failed (exit $_MIGRATE_JOB_EXIT) — nothing was stopped or rolled out"

  _migrate_job check "${MIGRATE_CHECK_TIMEOUT_SECS:-600}" "${_MIGRATE_SCRIPT[@]}" --check
  case "$_MIGRATE_JOB_EXIT" in
    0)
      printf 'catch_up=none\nwriters_down=false\n' >> "$GITHUB_OUTPUT"
      ci_ok "deploy migrate: no conversation needs a catch-up — the rollout runs with no downtime"
      return 0
      ;;
    "$_MIGRATE_CATCH_UP_NEEDED") echo "catch_up=needed" >> "$GITHUB_OUTPUT" ;;
    *) ci_die "deploy migrate: the check job failed (exit $_MIGRATE_JOB_EXIT) — nothing was stopped or rolled out" ;;
  esac

  local svc replicas
  for svc in "${_MIGRATE_WRITERS[@]}"; do
    replicas=$(_migrate_docker service inspect "$svc" --format '{{.Spec.Mode.Replicated.Replicas}}') \
      || ci_die "deploy migrate: cannot read the replica count of $svc"
    _MIGRATE_RESTORE="${_MIGRATE_RESTORE:+$_MIGRATE_RESTORE }$svc=$replicas"
  done
  echo "deploy migrate: a catch-up is needed — stopping the old writers (${_MIGRATE_WRITERS[*]})"
  _migrate_docker service scale --detach "${_MIGRATE_WRITERS[@]/%/=0}" > /dev/null \
    || ci_die "deploy migrate: could not scale the old writers to 0"
  for svc in "${_MIGRATE_WRITERS[@]}"; do
    _migrate_await "$svc" le 0 \
      || ci_die "deploy migrate: $svc still has Running tasks after ${MIGRATE_WRITERS_TIMEOUT_SECS:-300}s — not migrating under a live writer"
  done

  _migrate_job catch-up "${MIGRATE_CATCH_UP_TIMEOUT_SECS:-1800}" "${_MIGRATE_SCRIPT[@]}"
  [[ "$_MIGRATE_JOB_EXIT" = 0 ]] \
    || ci_die "deploy migrate: the catch-up job failed (exit $_MIGRATE_JOB_EXIT) — the new image was not rolled out"
  _MIGRATE_CAUGHT_UP=true
  echo "writers_down=true" >> "$GITHUB_OUTPUT"
  ci_ok "deploy migrate: caught up; the writers stay stopped until the rollout starts them on the new image"
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

  is_deployed_repo() {
    local name
    for name in "${APPS_IMAGE_REPOS[@]}" "${BOTS_IMAGE_REPOS[@]}" "$GRAFANA_IMAGE_REPO"; do
      [[ "$1" == "$GHCR_NAMESPACE/$name" ]] && return 0
    done
    return 1
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
        # image each service now runs and re-point its repo's :latest at it.
        # Every service on one of OUR repos counts, grafana included, rather
        # than a hand-kept name list that once left grafana's :latest on the
        # build it had just been rolled away from. Keyed by repo and pinned by
        # DIGEST: deduping whole `repo:tag@digest` refs let services sharing a
        # repo issue one retag each, so :latest landed on whichever sorted last.
        local services svc image repo targets="" conflicts
        services="$(docker --context "$DOCKER_CONTEXT" stack services "$STACK" --format '{{.Name}}')"
        while IFS= read -r svc; do
          [[ -n "$svc" ]] || continue
          image="$(docker --context "$DOCKER_CONTEXT" service inspect "$svc" \
            --format '{{.Spec.TaskTemplate.ContainerSpec.Image}}')"
          repo="$(repo_of "$image")"
          is_deployed_repo "$repo" || continue
          if [[ "$image" == *@* ]]; then
            targets+="$repo $repo@${image#*@}"$'\n'
          else
            targets+="$repo $image"$'\n'
          fi
        done <<< "$services"
        targets="$(printf '%s' "$targets" | sort -u)"
        if [[ -z "$targets" ]]; then
          echo "::error::rolled-back retag: no service in stack $STACK runs one of our images"
          exit 1
        fi
        # One repo, two images: prod is split across builds and :latest can
        # name only one of them, so moving it would make the alias a guess.
        conflicts="$(awk '{n[$1]++; l[$1] = l[$1] $2 "\n"} END {for (r in n) if (n[r] > 1) printf "%s", l[r]}' <<< "$targets")"
        if [[ -n "$conflicts" ]]; then
          echo "::error::rolled-back retag: services on one repo run different images — :latest left unchanged"
          printf '%s\n' "$conflicts"
          exit 1
        fi
        while IFS=' ' read -r _repo target; do
          retag "$target"
        done <<< "$targets"
      fi
      ;;

    *)
      echo "::error::retag-latest-alias: unknown mode '$MODE' (use from-env or rolled-back)"
      exit 1
      ;;
  esac
}

cmd_smoke() {
  : "${PROD_ORIGIN:?PROD_ORIGIN is required}"
  : "${PROD_WEB_ORIGIN:?PROD_WEB_ORIGIN is required}"
  # Extra arguments pass through (prod_smoke.py --help); the workflow passes none.
  python3 -I "$(dirname "$0")/lib/prod_smoke.py" --api "$PROD_ORIGIN" --web "$PROD_WEB_ORIGIN" "$@" \
    || ci_die "deploy smoke: production fails an anonymous visitor, or the smoke could not decide (verdict above)"
  ci_ok "deploy smoke: OK ($PROD_ORIGIN and $PROD_WEB_ORIGIN answer an anonymous visitor as expected; warnings above, if any)"
}

# A message is a state, its impact, the cause, the action and what clears it —
# eight content lines, no prose. Past that nobody reads it and the template has
# drifted, so notify refuses to send (see the guard in cmd_notify).
_NOTIFY_MAX_LINES=8
# Continuation lines sit under the first line's text: "Cause: " is seven
# characters, so eight spaces aligns just past it on every block.
_NOTIFY_INDENT="        "

# _notify_headline <glyph> <title> — the one line that names the state, with
# SUBJECT's specifics after it when the caller has any.
_notify_headline() {
  if [[ -n "${SUBJECT:-}" ]]; then
    printf '%s %s — %s\n' "$1" "$2" "$SUBJECT"
  else
    printf '%s %s\n' "$1" "$2"
  fi
}

# _notify_block <label> <text> — one labelled paragraph: `Label: first line`,
# every further line aligned under it. Empty text prints nothing at all, so a
# state with nothing to clear simply has no Clears-when line; a blank line
# inside a field (a YAML block scalar keeps its trailing newline) is dropped
# rather than sent as an indented whitespace line.
_notify_block() {
  local label="$1" text="$2" line first=true
  [[ -n "$text" ]] || return 0
  while IFS= read -r line; do
    [[ -n "$line" ]] || continue
    if [[ "$first" = true ]]; then
      printf '%s: %s\n' "$label" "$line"
      first=false
    else
      printf '%s%s\n' "$_NOTIFY_INDENT" "$line"
    fi
  done <<< "$text"
}

# _notify_state_color — the state's own colour. Read outside the command
# substitution that renders the body, so the choice is not lost with it.
_notify_state_color() {
  case "$STATE" in
    deploy_blocked | deploy_failed) printf '%s\n' "#ff6b6b" ;;
    deploy_succeeded | recovered) printf '%s\n' "#48f442" ;;
    *)
      ci_die "deploy notify: unknown STATE '$STATE' (deploy_blocked|deploy_failed|deploy_succeeded|recovered)"
      ;;
  esac
}

# _notify_state_message — one template per state, on stdout. Every field a state
# cannot do without is required here rather than defaulted: a missing one is
# template drift, and an empty slot would send a message that says nothing.
_notify_state_message() {
  local glyph title cause_label clears_required=false
  case "$STATE" in
    deploy_blocked) glyph="⛔"; title="DEPLOY BLOCKED"; cause_label="Cause"; clears_required=true ;;
    deploy_failed) glyph="❌"; title="DEPLOY FAILED"; cause_label="Cause"; clears_required=true ;;
    deploy_succeeded) glyph="✅"; title="DEPLOY SUCCEEDED"; cause_label="Shipped" ;;
    recovered) glyph="🟢"; title="RECOVERED"; cause_label="Cause" ;;
    *) ci_die "deploy notify: unknown STATE '$STATE' (deploy_blocked|deploy_failed|deploy_succeeded|recovered)" ;;
  esac

  # Required, not defaulted: a missing field is template drift, and an empty slot
  # sends a message that says nothing.
  : "${IMPACT:?IMPACT is required for STATE=$STATE}"
  : "${CAUSE:?CAUSE is required for STATE=$STATE}"
  : "${ACTION:?ACTION is required for STATE=$STATE}"
  [[ "$clears_required" = false ]] || : "${CLEARS_WHEN:?CLEARS_WHEN is required for STATE=$STATE}"

  _notify_headline "$glyph" "$title"
  _notify_block "Prod" "$IMPACT"
  echo
  # CAUSE is the antecedent: for a success it is what shipped.
  _notify_block "$cause_label" "$CAUSE"
  _notify_block "Do" "$ACTION"
  _notify_block "Clears when" "${CLEARS_WHEN:-}"
}

cmd_notify() {
  USERNAME="${USERNAME:-Gaia Deploy Bot}"

  local message
  if [[ -n "${STATE:-}" ]]; then
    COLOR="${COLOR:-$(_notify_state_color)}"
    message="$(_notify_state_message)"
  else
    # Legacy callers still get the free-text path they were written against.
    : "${MESSAGE:?MESSAGE (or STATE) is required}"
    : "${COLOR:?COLOR is required}"
    message="$MESSAGE"
  fi

  local link="${RUN_LINK:-}"
  if [[ -z "$link" ]] && [[ -n "${GITHUB_RUN_ID:-}" ]]; then
    link="${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}/actions/runs/${GITHUB_RUN_ID}"
  fi
  [[ -n "$link" ]] && message+=$'\n'"$link"

  # Always log the full message first, so the run itself records what was (or
  # failed to be) delivered even when a webhook call is lost.
  echo "Deploy notification:"
  printf '%s\n' "$message"

  # Blank lines separate blocks and are not content; everything else is. Loud on
  # overflow: a template that grew past its budget must fail here, in the run
  # that can be fixed, not arrive in the channel as an essay.
  local content_lines
  content_lines=$(grep -c . <<< "$message" || true)
  if (( content_lines > _NOTIFY_MAX_LINES )); then
    ci_die "deploy notify: message is ${content_lines} content lines (max ${_NOTIFY_MAX_LINES}) — shorten the ${STATE:-MESSAGE} template"
  fi

  if [[ "${DRY_RUN:-}" = "true" ]]; then
    ci_ok "deploy notify: dry run — rendered and length-guarded, not delivered"
    return 0
  fi

  # Discord and Slack embed limits sit near 4096 chars — truncate instead of 400ing.
  if [[ "${#message}" -gt 4000 ]]; then
    message="${message:0:4000}"$'\n'"…(truncated)"
  fi

  local failed=() payload response
  if [[ -z "${DISCORD_WEBHOOK:-}" ]]; then
    failed+=("DISCORD_WEBHOOK is unset")
  else
    payload=$(jq -n --arg u "$USERNAME" --arg d "$message" --argjson c "$((16#${COLOR#\#}))" \
      '{username: $u, embeds: [{description: $d, color: $c}]}')
    # wait=true makes Discord return the created message, so the log proves
    # delivery and names the channel instead of trusting a bare 204.
    local sep="?"
    [[ "$DISCORD_WEBHOOK" == *\?* ]] && sep="&"
    if response=$(post_webhook Discord "${DISCORD_WEBHOOK}${sep}wait=true" "$payload"); then
      ci_ok "deploy notify: Discord OK (message $(jq -r .id <<< "$response") in channel $(jq -r .channel_id <<< "$response"))"
    else
      failed+=("Discord")
    fi
  fi

  if [[ -z "${SLACK_WEBHOOK:-}" ]]; then
    failed+=("SLACK_WEBHOOK is unset")
  else
    # Discord markdown bolds with **, Slack mrkdwn with a single *.
    payload=$(jq -n --arg t "${message//\*\*/*}" --arg c "$COLOR" --arg f "${message%%$'\n'*}" \
      '{attachments: [{color: $c, fallback: $f, text: $t, mrkdwn_in: ["text"]}]}')
    if post_webhook Slack "$SLACK_WEBHOOK" "$payload" > /dev/null; then
      ci_ok "deploy notify: Slack OK"
    else
      failed+=("Slack")
    fi
  fi

  if [[ "${#failed[@]}" -gt 0 ]]; then
    ci_die "deploy notify: not delivered — $(IFS=,; echo "${failed[*]}")"
  fi
}

# cmd_failing_checks <sha> [max] — the check-runs that failed on <sha>, as the
# cause lines a blocked message renders: `"<name> failed on <short sha>"`, then
# `"→ <html_url>"`, one pair per check.
#
# <max> (default 3) bounds how many are named, the rest collapsing to a count on
# the last name line — notify's eight-line budget is the whole message's, and a
# red gate can fail a dozen checks. "Required" is not in this payload (it lives
# in the branch-protection rule), so the discriminator is "failed": a skipped or
# neutral check is not a cause.
#
# Fails non-zero when the request does, because an empty answer from a broken
# lookup reads exactly like "nothing failed" and would send a cause-less alarm.
cmd_failing_checks() {
  local sha="${1:?usage: deploy.sh failing-checks <sha> [max]}"
  local max="${2:-3}"
  : "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
  local short="${sha:0:8}" rows name url shown=0 total

  if ! rows=$(gh api --paginate "repos/$GITHUB_REPOSITORY/commits/$sha/check-runs?per_page=100&filter=latest" \
    -H 'Accept: application/vnd.github+json' \
    --jq '.check_runs[]
      | select(.conclusion as $c
          | ["failure", "timed_out", "cancelled", "action_required", "startup_failure", "stale"] | index($c))
      | [.name, .html_url] | @tsv'); then
    ci_die "deploy failing-checks: the check-runs request for $short failed — the cause is unknown, not absent"
  fi

  if [[ -z "$rows" ]]; then
    echo "no failing check-runs reported on $short"
    return 0
  fi

  total=$(grep -c . <<< "$rows" || true)
  # while-read, not mapfile: macOS bash 3.2 (pytest.sh makes the same choice).
  while IFS=$'\t' read -r name url; do
    shown=$((shown + 1))
    if (( shown == max && total > max )); then
      printf '%s failed on %s (+%d more)\n' "$name" "$short" "$((total - max))"
    else
      printf '%s failed on %s\n' "$name" "$short"
    fi
    printf '→ %s\n' "$url"
    (( shown < max )) || break
  done <<< "$rows"
}

# image_commit <ref> — the GIT_COMMIT_SHA the image was built with (the same
# variable env_context()/resolveCommit() read at runtime). {{json .Image}} is one
# config for a single-platform image and a platform-keyed map for an index.
image_commit() {
  local ref="$1" shas
  shas=$(docker buildx imagetools inspect "$ref" --format '{{json .Image}}' \
    | jq -r '(if has("config") then [.] else [.[]] end)
        | [.[].config.Env // [] | .[] | select(startswith("GIT_COMMIT_SHA=")) | ltrimstr("GIT_COMMIT_SHA=")]
        | unique | .[]')
  [[ -n "$shas" ]] || ci_die "image $ref carries no GIT_COMMIT_SHA — cannot tell which commit it runs"
  [[ "$shas" != *$'\n'* ]] || ci_die "image $ref platforms disagree on GIT_COMMIT_SHA: ${shas//$'\n'/, }"
  echo "$shas"
}

# served_commit <url> — the `commit` a /health endpoint reports, empty when it
# reports none or is unreachable.
served_commit() {
  curl -fsS --connect-timeout 5 --max-time 10 "$1" | jq -r '.commit // empty'
}

# await_commit <url> <full sha> — passes once VERIFY_CONSECUTIVE spaced reads in a
# row serve the sha's short form. Replica coverage is convergence's job (every
# running task on the new spec, so one image); this proves that image serves the
# commit, through the public route a user hits.
await_commit() {
  local url="$1" want="${2:0:8}" got streak=0
  local deadline=$(( $(date +%s) + ${VERIFY_TIMEOUT_SECS:-180} ))
  while :; do
    got=$(served_commit "$url" || true)
    if [[ "$got" == "$want" ]]; then
      streak=$((streak + 1))
      (( streak >= ${VERIFY_CONSECUTIVE:-5} )) && break
    else
      streak=0
      if (( $(date +%s) >= deadline )); then
        ci_die "$url serves commit '${got:-<none>}', expected $want — prod is not running the deployed image"
      fi
    fi
    sleep "${VERIFY_POLL_SECS:-5}"
  done
  ci_ok "deploy verify-commit: $url serves $want"
}

cmd_verify_commit() {
  : "${PROD_ORIGIN:?PROD_ORIGIN is required}"
  : "${GITHUB_OUTPUT:?GITHUB_OUTPUT is required}"
  local apps_sha bots_sha repo
  apps_sha=$(image_commit "$GHCR_NAMESPACE/${APPS_IMAGE_REPOS[0]}:${APPS_IMAGE_TAG:-latest}")
  await_commit "$PROD_ORIGIN/health" "$apps_sha"
  # Bots are only redeployed when their tag was passed (see the converge step).
  if [[ -n "${BOTS_IMAGE_TAG:-}" ]]; then
    for repo in "${BOTS_IMAGE_REPOS[@]}"; do
      bots_sha=$(image_commit "$GHCR_NAMESPACE/$repo:$BOTS_IMAGE_TAG")
      await_commit "$PROD_ORIGIN/bots/${repo#gaia-bot-}/health" "$bots_sha"
    done
  fi
  echo "commit=$apps_sha" >> "$GITHUB_OUTPUT"
}

# alert_rule_uid_diff <expected uids> <shipped uids> — newline lists in, one
# `missing <uid>` / `extra <uid>` line per difference out; empty when equal.
alert_rule_uid_diff() {
  comm -23 <(sort -u <<< "$1") <(sort -u <<< "$2") | sed 's/^/missing /'
  comm -13 <(sort -u <<< "$1") <(sort -u <<< "$2") | sed 's/^/extra /'
}

_GRAFANA_SERVICE="gaia-prod_grafana"
_GRAFANA_RULES_FILE="/etc/grafana/provisioning/alerting/alert-rules.yaml"

# alert_rule_uids — the rule uids in the rules file on stdin. Every rule opens its
# list item with its uid; yq is not on every runner that runs this.
alert_rule_uids() {
  sed -nE 's/^[[:space:]]*-[[:space:]]+uid:[[:space:]]+([A-Za-z0-9_-]+)[[:space:]]*$/\1/p'
}

# shipped_alert_rule_uids — the uids in the rules file the running grafana task was
# built with. Read off the image, so no Grafana login is involved.
shipped_alert_rule_uids() {
  local cid
  cid=$(docker --context prod ps -q --filter "label=com.docker.swarm.service.name=$_GRAFANA_SERVICE")
  # none is a task not up yet, two is Swarm mid-roll: neither is the release to judge
  [[ "$(grep -c . <<< "$cid")" == 1 ]] || return 1
  docker --context prod exec "$cid" cat "$_GRAFANA_RULES_FILE" | alert_rule_uids
}

cmd_verify_alert_rules() {
  local file="${ALERT_RULES_FILE:-infra/docker/observability/grafana/provisioning/alerting/alert-rules.yaml}"
  [[ -s "$file" ]] || ci_die "deploy verify-alert-rules: $file is missing or empty"
  local expected shipped="" diff
  expected=$(alert_rule_uids < "$file")
  [[ -n "$expected" ]] || ci_die "deploy verify-alert-rules: $file declares no rule uids"
  local deadline=$(( $(date +%s) + ${GRAFANA_VERIFY_TIMEOUT_SECS:-120} ))
  # the old task still answers while Swarm rolls the new one, so a difference is retried too
  until shipped=$(shipped_alert_rule_uids) && diff=$(alert_rule_uid_diff "$expected" "$shipped") && [[ -z "$diff" ]]; do
    if (( $(date +%s) >= deadline )); then
      [[ -n "$shipped" ]] || ci_die "deploy verify-alert-rules: the $_GRAFANA_SERVICE task has no rules at $_GRAFANA_RULES_FILE"
      ci_die "deploy verify-alert-rules: the running Grafana image carries different rules than $file: ${diff//$'\n'/, }"
    fi
    sleep "${GRAFANA_VERIFY_POLL_SECS:-5}"
  done
  ci_ok "deploy verify-alert-rules: the running Grafana image carries exactly the $(wc -l <<< "$expected" | tr -d ' ') rules in $file"
}

cmd_served_commit() {
  : "${PROD_ORIGIN:?PROD_ORIGIN is required}"
  : "${GITHUB_OUTPUT:?GITHUB_OUTPUT is required}"
  local previous
  # Informational (it scopes the success message's change list): an
  # unreachable prod is exactly when a fix must still be able to deploy.
  previous=$(served_commit "$PROD_ORIGIN/health") \
    || ci_warn "could not read the commit prod serves before this deploy"
  echo "previous=$previous" >> "$GITHUB_OUTPUT"
}

# cmd_changelog — commit subjects (PR titles for squash merges) from PREVIOUS to
# COMMIT; just COMMIT's own when the previous commit is unknown.
cmd_changelog() {
  : "${COMMIT:?COMMIT is required}"
  : "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
  : "${GITHUB_OUTPUT:?GITHUB_OUTPUT is required}"
  local subjects
  if [[ -n "${PREVIOUS:-}" ]]; then
    subjects=$(gh api "repos/$GITHUB_REPOSITORY/compare/$PREVIOUS...$COMMIT" \
      --jq '.commits | reverse | .[].commit.message | split("\n")[0]')
  else
    subjects=$(gh api "repos/$GITHUB_REPOSITORY/commits/$COMMIT" --jq '.commit.message | split("\n")[0]')
  fi
  local total
  total=$(grep -c . <<< "$subjects" || true)
  {
    echo "changes<<CHANGES_EOF"
    if (( total == 0 )); then
      echo "- no new commits since the previous deploy"
    else
      head -n 15 <<< "$subjects" | sed 's/^/- /'
    fi
    if (( total > 15 )); then
      echo "- …and $((total - 15)) more"
    fi
    echo "CHANGES_EOF"
  } >> "$GITHUB_OUTPUT"
}

# Written by an EXIT trap so a reap already done is reported even when a later
# request fails the step.
UNWEDGE_REAPED=""

cmd_unwedge() {
  : "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
  : "${GITHUB_RUN_ID:?GITHUB_RUN_ID is required}"
  : "${GITHUB_OUTPUT:?GITHUB_OUTPUT is required}"
  # A releasable gate clears in seconds (waiting -> queued within ~1 s on every
  # healthy deploy), so 15 min is far past anything legitimate.
  local limit="${STUCK_LIMIT_SECS:-900}"
  local api="repos/${GITHUB_REPOSITORY}/actions/runs"
  local run_ids run_id releasable age next_check

  trap 'echo "reaped=${UNWEDGE_REAPED}" >> "$GITHUB_OUTPUT"' EXIT

  # Re-check until no gate is still inside the limit: a push that lands 10 min
  # into a wedge must stay until it can clear it, or its own deploy queues
  # behind that run with nobody left to free it.
  while :; do
    run_ids="$(gh api "${api}?branch=master&status=waiting&per_page=100" \
      --jq '.workflow_runs[] | select(.id != (env.GITHUB_RUN_ID | tonumber)) | .id')"
    next_check=0

    for run_id in $run_ids; do
      # Force-cancel is not instant, so a reaped run can still be listed.
      [[ " ${UNWEDGE_REAPED} " == *" ${run_id} "* ]] && continue

      # Empty means no deployment gate at all; "true" means a human or a timer
      # can still release it. Only a gate nothing can release is a wedge.
      releasable="$(gh api "${api}/${run_id}/pending_deployments" \
        --jq 'if length == 0 then "" else (map(.wait_timer > 0 or (.reviewers | length) > 0) | any) end')"
      if [[ "$releasable" != "false" ]]; then
        echo "unwedge: run ${run_id} is waiting on a gate that can be released (${releasable:-no deployment gate}) — leaving it"
        continue
      fi

      age="$(gh api "${api}/${run_id}/jobs?filter=latest&per_page=100" \
        --jq '[.jobs[] | select(.status == "waiting") | now - (.started_at | fromdateiso8601)] | max // 0 | floor')"
      if (( age <= limit )); then
        echo "unwedge: run ${run_id} gate waiting ${age}s (limit ${limit}s) — re-checking once it crosses the limit"
        if (( next_check == 0 || limit - age + 1 < next_check )); then
          next_check=$(( limit - age + 1 ))
        fi
        continue
      fi

      # Safe to force: a job parked on its environment gate never reached a
      # runner, so nothing has touched production.
      gh api -X POST "${api}/${run_id}/force-cancel" > /dev/null
      ci_warn "unwedge: force-cancelled run ${run_id} — its deployment gate had no reviewers or timer and sat waiting ${age}s"
      UNWEDGE_REAPED="${UNWEDGE_REAPED:+$UNWEDGE_REAPED }${run_id}"
    done

    (( next_check == 0 )) && break
    sleep "$next_check"
  done

  ci_ok "deploy unwedge: OK (reaped: ${UNWEDGE_REAPED:-none})"
}

usage() {
  # The header comment, up to the line before `set -euo pipefail`.
  sed -n '2,/^set -euo pipefail$/p' "$0" | sed '$d' >&2
}

main() {
  local sub="${1:-}"
  shift || true
  case "$sub" in
    plan)   cmd_plan "$@" ;;
    stack)  _cmd_swarm_stack deploy "$@" ;;
    migrate) cmd_migrate "$@" ;;
    verify) _cmd_swarm_stack verify "$@" ;;
    smoke)  cmd_smoke "$@" ;;
    retag)  cmd_retag "$@" ;;
    notify) cmd_notify "$@" ;;
    failing-checks) cmd_failing_checks "$@" ;;
    served-commit) cmd_served_commit "$@" ;;
    verify-commit) cmd_verify_commit "$@" ;;
    verify-alert-rules) cmd_verify_alert_rules "$@" ;;
    changelog) cmd_changelog "$@" ;;
    unwedge) cmd_unwedge "$@" ;;
    *)
      echo "deploy.sh: unknown subcommand '${sub}'" >&2
      usage
      exit 2
      ;;
  esac
}

main "$@"
