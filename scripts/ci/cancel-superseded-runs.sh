#!/usr/bin/env bash
# Cancel older queued/in-progress runs of this workflow on the same branch.
#
# Why not `concurrency.cancel-in-progress`: with a shared group the NEW run sits
# in "pending" until the OLD run's cancellation completes. On the self-hosted
# box a cancelled pytest step wedges the runner worker until the listener's
# 5-minute cancellation timeout (measured three times on 2026-08-28), so every
# push cost the next run 5 minutes before its first job started. The workflows
# now use a per-SHA concurrency group and this step cancels the superseded runs
# asynchronously: the new run starts at once, the old one dies on its own time.
# Runs on master coalesce the same way ("final verification wins").
#
# Env: GITHUB_TOKEN (actions: write), GITHUB_REPOSITORY, GITHUB_RUN_ID,
#      GITHUB_WORKFLOW_REF (…/.github/workflows/<file>@<ref>), GITHUB_HEAD_REF
#      or GITHUB_REF_NAME.
set -euo pipefail

workflow_file="$(echo "${GITHUB_WORKFLOW_REF}" | sed -E 's#.*/\.github/workflows/([^@]+)@.*#\1#')"
branch="${GITHUB_HEAD_REF:-${GITHUB_REF_NAME}}"
event="${GITHUB_EVENT_NAME:-}"

older="$(gh api --paginate \
  "repos/${GITHUB_REPOSITORY}/actions/workflows/${workflow_file}/runs?branch=${branch}&event=${event}&per_page=50" \
  --jq ".workflow_runs[] | select(.id < ${GITHUB_RUN_ID}) | select(.status == \"queued\" or .status == \"in_progress\" or .status == \"waiting\" or .status == \"pending\") | .id")"

if [ -z "$older" ]; then
  echo "no superseded ${workflow_file} runs on ${branch}"
  exit 0
fi
for id in $older; do
  if gh api -X POST "repos/${GITHUB_REPOSITORY}/actions/runs/${id}/cancel" > /dev/null 2>&1; then
    echo "cancelled superseded run ${id}"
  else
    echo "::warning::could not cancel run ${id} (already finishing?)"
  fi
done
