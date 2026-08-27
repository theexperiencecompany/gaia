#!/usr/bin/env bash
# Dispatches the CLI publish workflow and blocks until the version is on npm.
#
# createWorkflowDispatch returns 204 the moment GitHub *accepts* the request,
# so a fire-and-forget dispatch reports success even when the publish it
# started fails. That is exactly how @heygaia/cli sat unpublished for five
# consecutive releases while Release Please stayed green.
#
# The dispatch API returns no run id, and nothing in a run's metadata ties it
# back to the caller — so any attempt to pick "our" run out of the recent list
# is a guess that a concurrent dispatch (a manual catch-up publish during a
# release, say) silently breaks. Instead this waits on the outcome that
# actually matters and that no other run can fake: the version being on npm.
# Run identity never enters into it.
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
PACKAGE="@heygaia/cli"
POLL_SECONDS=20
TIMEOUT_SECONDS=900

published() {
  # Exits non-zero when the exact version is absent from the registry.
  npm view "${PACKAGE}@${VERSION}" version >/dev/null 2>&1
}

# Counts publish runs that have not finished yet — any run, not just one we
# started. It only ever makes us wait longer, never mistake someone else's
# result for ours.
active_runs() {
  gh run list --workflow "$WORKFLOW" --limit 20 --json status \
    --jq '[.[] | select(.status != "completed")] | length' 2>/dev/null || echo 0
}

if published; then
  echo "${PACKAGE}@${VERSION} is already on npm — nothing to dispatch."
  exit 0
fi

echo "Dispatching $WORKFLOW for $TAG ($VERSION)"
gh workflow run "$WORKFLOW" --ref master -f "tag=$TAG" -f "version=$VERSION"

runs_url="${GITHUB_SERVER_URL:-https://github.com}/${GITHUB_REPOSITORY:-theexperiencecompany/gaia}/actions/workflows/${WORKFLOW}"
deadline=$((SECONDS + TIMEOUT_SECONDS))
seen_active=0

while ((SECONDS < deadline)); do
  sleep "$POLL_SECONDS"

  if published; then
    echo "${PACKAGE}@${VERSION} published."
    exit 0
  fi

  active=$(active_runs)
  if ((active > 0)); then
    # A publish is still running; keep waiting for it to land.
    seen_active=1
  elif ((seen_active == 1)); then
    # We watched a publish run start and finish, and the version still is not
    # on the registry — that is a failed publish, reported now rather than at
    # the timeout.
    echo "::error::Publish finished but ${PACKAGE}@${VERSION} is not on npm. See ${runs_url}"
    exit 1
  fi
done

echo "::error::Timed out after ${TIMEOUT_SECONDS}s waiting for ${PACKAGE}@${VERSION} on npm. See ${runs_url}"
exit 1
