#!/usr/bin/env bash
# Dispatches the CLI publish workflow and blocks on its result.
#
# createWorkflowDispatch returns 204 the moment GitHub *accepts* the request,
# so a fire-and-forget dispatch reports success even when the publish it
# started fails. That is exactly how @heygaia/cli sat unpublished for five
# consecutive releases while Release Please stayed green. This waits for the
# run it started and exits with that run's conclusion, so a failed publish
# turns the release workflow red.
#
# Inputs (env):
#   GH_TOKEN  token with actions:write (required)
#   TAG       release tag, e.g. cli-v0.4.0 (required)
#   VERSION   release version, e.g. 0.4.0 (required)
set -euo pipefail

: "${GH_TOKEN:?GH_TOKEN is required}"
: "${TAG:?TAG is required}"
: "${VERSION:?VERSION is required}"

WORKFLOW="publish-cli.yml"
# Second-resolution timestamps can tie with the run's own createdAt, so look
# slightly into the past rather than risk filtering out the run we started.
since=$(date -u -d '30 seconds ago' +%Y-%m-%dT%H:%M:%SZ)

echo "Dispatching $WORKFLOW for $TAG ($VERSION)"
gh workflow run "$WORKFLOW" --ref master -f "tag=$TAG" -f "version=$VERSION"

run_id=""
for _ in $(seq 1 30); do
  sleep 5
  run_id=$(gh run list --workflow "$WORKFLOW" --event workflow_dispatch \
    --created ">$since" --limit 10 --json databaseId,createdAt \
    --jq 'sort_by(.createdAt) | last | .databaseId // empty')
  [[ -n "$run_id" ]] && break
done

if [[ -z "$run_id" ]]; then
  echo "::error::Dispatched $WORKFLOW but no run appeared within 150s — publish status is unknown."
  exit 1
fi

echo "Watching run $run_id"
# --exit-status propagates the run's conclusion as this step's exit code.
gh run watch "$run_id" --exit-status --interval 15
