#!/usr/bin/env bash
# queued-job-watchdog.sh — never leave a run parked on an offline home box.
#
# select-runner decides once, at the start of the run. If the box dies between
# that decision and pickup (reboot, uplink drop, runner units stopped), GitHub
# keeps the self-hosted jobs `queued` for up to 24 h — timeout-minutes only
# starts once a job is picked up — and the PR check sits pending all day.
#
# Runs on ubuntu-latest alongside the compute lanes: polls this run's jobs and,
# when any job has been queued longer than QUEUE_LIMIT_SECS, cancels the run
# with an error that says what to do (re-run with force_github=true). Exits
# quietly as soon as no job is queued any more.
#
# Env: GITHUB_TOKEN (actions: write), GITHUB_REPOSITORY, GITHUB_RUN_ID,
#      WATCHDOG_JOB_NAME (this job's display name, excluded from the check),
#      QUEUE_LIMIT_SECS (default 480), POLL_SECS (default 30).
set -euo pipefail

LIMIT="${QUEUE_LIMIT_SECS:-480}"
POLL="${POLL_SECS:-30}"
: "${WATCHDOG_JOB_NAME:?WATCHDOG_JOB_NAME is required}"
export WATCHDOG_JOB_NAME
API="repos/${GITHUB_REPOSITORY}/actions/runs/${GITHUB_RUN_ID}"

while :; do
  # name<TAB>status<TAB>created_at, one job per line, this watchdog excluded.
  jobs="$(gh api "${API}/jobs?per_page=100" \
    --jq '.jobs[] | select(.name != env.WATCHDOG_JOB_NAME) | [.name, .status, .created_at] | @tsv')"
  queued="$(printf '%s\n' "$jobs" | awk -F'\t' '$2 == "queued"')"
  if [[ -z "$queued" ]]; then
    echo "watchdog: no queued jobs — every lane was picked up"
    exit 0
  fi
  now="$(date -u +%s)"
  while IFS=$'\t' read -r name _status created; do
    [[ -n "$name" ]] || continue
    age=$(( now - $(date -u -d "$created" +%s) ))
    echo "watchdog: '$name' queued for ${age}s (limit ${LIMIT}s)"
    if (( age > LIMIT )); then
      echo "::error::'$name' has been queued for ${age}s — the home runner accepted the run but is not picking jobs up. Cancelling; re-run with force_github=true to use GitHub-hosted runners."
      gh api -X POST "${API}/cancel" >/dev/null
      exit 1
    fi
  done <<< "$queued"
  sleep "$POLL"
done
