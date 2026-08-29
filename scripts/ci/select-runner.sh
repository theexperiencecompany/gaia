#!/usr/bin/env bash
# select-runner.sh — decide whether the home self-hosted runner is usable,
# with graceful fallback to GitHub-hosted runners.
#
# Elegant fallback contract:
#   * Runs entirely on ubuntu-latest (no Tailscale needed from GH side).
#   * Probes GitHub Actions API for runner liveness — no inbound ports, no SSH.
#   * Timeout + retry so a flaky API never blocks the lane.
#   * Downstream jobs use      runs-on: ${{ fromJSON(needs.select-runner.outputs.runner) }}
#   * Fallback is total: never leaves a job queued on an offline self-hosted label.
#
# Env:
#   GITHUB_TOKEN            — required (Actions-provided). Repo scope is enough.
#   GITHUB_REPOSITORY       — owner/repo
#   RUNNER_LABEL            — label to probe (default: gaia-home)
#   FALLBACK_RUNNER         — JSON array used when home is unavailable (default: ["ubuntu-latest"])
#   FORCE_HOME              — if "true", fail loudly instead of falling back (for smoke tests)
#   FORCE_GITHUB            — if "true", skip the probe and select the fallback (exercises the GitHub path)
#   PR_HEAD_REPO            — owner/repo of the PR head; a fork never gets the home box
#   PR_AUTHOR_ASSOCIATION   — github.event.pull_request.author_association; only OWNER/MEMBER get the box
#   GITHUB_ACTOR            — bots (dependabot[bot], …) never get the box
#
# Outputs (via $GITHUB_OUTPUT when present, else stdout):
#   runner              — JSON array string, e.g. '["self-hosted","gaia-home"]'
#   runner_label        — human label: gaia-home | ubuntu-latest
#   is_self_hosted      — true | false
#
# Step summary appended to $GITHUB_STEP_SUMMARY when available.
set -euo pipefail

LABEL="${RUNNER_LABEL:-gaia-home}"
# Via a variable: an inline `${X:-["ubuntu-latest"]}` loses its inner quotes
# to bash's quote removal and yields `[ubuntu-latest]`, which fromJSON rejects.
DEFAULT_FALLBACK='["ubuntu-latest"]'
FALLBACK="${FALLBACK_RUNNER:-$DEFAULT_FALLBACK}"
REPO="${GITHUB_REPOSITORY:-theexperiencecompany/gaia}"
TOKEN="${GITHUB_TOKEN:-}"
FORCE="${FORCE_HOME:-false}"
FORCE_GH="${FORCE_GITHUB:-false}"
HEAD_REPO="${PR_HEAD_REPO:-}"
AUTHOR_ASSOC="${PR_AUTHOR_ASSOCIATION:-}"
ACTOR="${GITHUB_ACTOR:-}"

# Sensible defaults when running locally (outside Actions)
if [[ -z "${GITHUB_OUTPUT:-}" ]]; then
  GITHUB_OUTPUT="/dev/stdout"
fi

API="https://api.github.com/repos/${REPO}/actions/runners"
FALLBACK_LABEL="$(echo "$FALLBACK" | tr -d '[]" ' | cut -d',' -f1)"

log() { echo "[select-runner] $*" >&2; }

emit() {
  local runner_json="$1" label="$2" is_self="$3" reason="$4"
  {
    echo "runner=${runner_json}"
    echo "runner_label=${label}"
    echo "is_self_hosted=${is_self}"
    echo "reason=${reason}"
  } >> "$GITHUB_OUTPUT"
  # Also expose as env for local debugging
  export SELECTED_RUNNER="$runner_json"
  export SELECTED_LABEL="$label"
}

summary() {
  local msg="$1"
  if [[ -n "${GITHUB_STEP_SUMMARY:-}" && -f "${GITHUB_STEP_SUMMARY:-}" ]]; then
    echo "$msg" >> "$GITHUB_STEP_SUMMARY"
  fi
  # Always log to stderr so it appears in job log
  log "$msg"
}

# Fork PRs never touch the box. The runner user's workspace, caches and network
# are shared state, and this is a public repo: code from outside it runs only on
# GitHub's throwaway VMs. Decided before the probe on purpose — a fork's token
# happens to be unable to list runners today, but that is an accident of token
# scopes, not a policy.
if [[ -n "$HEAD_REPO" && "$HEAD_REPO" != "$REPO" ]]; then
  log "PR head is $HEAD_REPO (fork of $REPO) — fork code never runs on the home box."
  emit "$FALLBACK" "$FALLBACK_LABEL" "false" "fork"
  summary "### Runner selection — fallback (fork)

- **Selected:** \`$FALLBACK\` — PR head \`$HEAD_REPO\` is not \`$REPO\`; fork code never runs on the home box
"
  exit 0
fi

# Only organisation members' pull requests run on the box. author_association
# is set by GitHub on the PR event: OWNER / MEMBER are the org, COLLABORATOR is
# an outside collaborator with write access, CONTRIBUTOR / FIRST_TIME_* / NONE
# is everyone else. Pushes carry no association: only write access can push,
# and the repo has no outside collaborators, so a push author is a member.
if [[ -n "$AUTHOR_ASSOC" && "$AUTHOR_ASSOC" != "OWNER" && "$AUTHOR_ASSOC" != "MEMBER" ]]; then
  log "PR author association is $AUTHOR_ASSOC (not OWNER/MEMBER) — only organisation members run on the home box."
  emit "$FALLBACK" "$FALLBACK_LABEL" "false" "untrusted-author"
  summary "### Runner selection — fallback (author not an organisation member)

- **Selected:** \`$FALLBACK\` — PR author association is \`$AUTHOR_ASSOC\`; only OWNER/MEMBER run on the home box
"
  exit 0
fi

# Bots (Dependabot, release bots) run code nobody reviewed before CI: their
# dependency bumps execute postinstall scripts. GitHub's throwaway VMs only.
if [[ "$ACTOR" == *"[bot]" ]]; then
  log "Actor $ACTOR is a bot — bots never run on the home box."
  emit "$FALLBACK" "$FALLBACK_LABEL" "false" "bot-actor"
  summary "### Runner selection — fallback (bot actor)

- **Selected:** \`$FALLBACK\` — actor \`$ACTOR\` is a bot; bots never run on the home box
"
  exit 0
fi

# Exercise the GitHub-hosted path on demand (workflow_dispatch force_github):
# the fallback only proves itself when it actually runs.
if [[ "$FORCE_GH" == "true" ]]; then
  log "FORCE_GITHUB=true — selecting $FALLBACK without probing."
  emit "$FALLBACK" "$FALLBACK_LABEL" "false" "forced-github"
  summary "### Runner selection — fallback (forced)

- **Selected:** \`$FALLBACK\` — \`force_github\` set on this dispatch
"
  exit 0
fi

if [[ -z "$TOKEN" ]]; then
  log "No GITHUB_TOKEN — cannot probe API. Falling back to $FALLBACK (local run)."
  emit "$FALLBACK" "$FALLBACK_LABEL" "false" "no-token"
  summary "### Runner selection — fallback (no token)

- **Selected:** \`$FALLBACK\` (no API token available)
- **Home label probed:** \`$LABEL\`
- **Reason:** local execution without GITHUB_TOKEN
"
  exit 0
fi

# Probe GitHub API with retries and hard timeout.
# We call /actions/runners once, then filter locally with jq/python.
ATTEMPTS=3
TIMEOUT_SECS=10
API_JSON=""
api_ok=false

for i in $(seq 1 $ATTEMPTS); do
  log "Probing $API (attempt $i/$ATTEMPTS, ${TIMEOUT_SECS}s timeout)..."
  # --max-time caps total, --connect-timeout caps TCP handshake
  if API_JSON=$(curl -sSf --max-time "$TIMEOUT_SECS" --connect-timeout 5 \
       -H "Authorization: Bearer $TOKEN" \
       -H "Accept: application/vnd.github+json" \
       -H "X-GitHub-Api-Version: 2022-11-28" \
       "$API" 2>&1); then
    api_ok=true
    break
  else
    log "Attempt $i failed: ${API_JSON:0:300}"
    API_JSON=""
    if (( i < ATTEMPTS )); then
      sleep $((i * 2))
    fi
  fi
done

if [[ "$api_ok" != "true" ]]; then
  log "API unavailable after $ATTEMPTS attempts. Falling back."
  if [[ "$FORCE" == "true" ]]; then
    echo "::error::HOME runner forced but API probe failed"
    exit 1
  fi
  emit "$FALLBACK" "$FALLBACK_LABEL" "false" "api-unavailable"
  summary "### Runner selection — fallback (API unavailable)

- **Selected:** \`$FALLBACK\`
- **Home label:** \`$LABEL\`
- **Reason:** GitHub API unreachable after ${ATTEMPTS} attempts (${TIMEOUT_SECS}s each)
- **Fallback after:** ~$((ATTEMPTS * (TIMEOUT_SECS + 2)))s worst case
"
  exit 0
fi

# Parse runners JSON. Prefer jq, fallback to python3.
#
# The home box runs several runner instances, all carrying the same label, so
# "is home usable?" is a question about the POOL, not about one instance:
# pick the first instance that is online AND idle. Selecting on the first
# matching instance regardless of state would fall back to GitHub whenever
# instance 1 happened to be busy, even with three others sitting idle.
#
# Emits: "<name>|<status>|<busy>|<os>|<labels>|<online_count>|<idle_count>|<total>"
parse_runner() {
  local json="$1" label="$2"
  if command -v jq >/dev/null 2>&1; then
    echo "$json" | jq -r --arg L "$label" '
      [.runners[]? | select(any(.labels[]?; .name == $L))] as $all
      | ($all | map(select(.status == "online"))) as $online
      | ($online | map(select(.busy == false))) as $idle
      | if ($all | length) == 0 then empty
        else
          (($idle | first) // ($online | first) // ($all | first)) as $pick
          | "\($pick.name)|\($pick.status)|\($pick.busy)|\($pick.os)|\($pick.labels | map(.name) | join(","))|\($online | length)|\($idle | length)|\($all | length)"
        end
    '
  else
    echo "$json" | python3 -c "
import json,sys
label=sys.argv[1]
d=json.load(sys.stdin)
all_=[r for r in d.get('runners',[]) if any(l.get('name')==label for l in r.get('labels',[]))]
if not all_:
    sys.exit(0)
online=[r for r in all_ if r.get('status')=='online']
idle=[r for r in online if r.get('busy') is False]
pick=(idle or online or all_)[0]
print('|'.join([
    str(pick.get('name')), str(pick.get('status')), str(pick.get('busy')).lower(),
    str(pick.get('os')), ','.join(l.get('name') for l in pick.get('labels', [])),
    str(len(online)), str(len(idle)), str(len(all_)),
]))
" "$label"
  fi
}

RUNNER_LINE="$(parse_runner "$API_JSON" "$LABEL" || true)"

if [[ -z "$RUNNER_LINE" ]]; then
  log "No runner matching label '$LABEL' registered. Fallback."
  if [[ "$FORCE" == "true" ]]; then
    echo "::error::No runner with label $LABEL"
    exit 1
  fi
  emit "$FALLBACK" "$FALLBACK_LABEL" "false" "not-registered"
  summary "### Runner selection — fallback (not registered)

- **Selected:** \`$FALLBACK\`
- **Home label:** \`$LABEL\`
- **Reason:** no runner with label \`$LABEL\` found (register via self-hosted-runner/setup.sh in the private gaia-infra repo)
"
  exit 0
fi

IFS='|' read -r R_NAME R_STATUS R_BUSY R_OS R_LABELS R_ONLINE R_IDLE R_TOTAL <<< "$RUNNER_LINE"
log "Home pool '$LABEL': ${R_IDLE} idle / ${R_ONLINE} online / ${R_TOTAL} registered — picked $R_NAME (status=$R_STATUS busy=$R_BUSY os=$R_OS)"

if [[ "$R_STATUS" == "online" && "$R_BUSY" == "false" ]]; then
  SELF_JSON='["self-hosted","'"$LABEL"'"]'
  log "Home runner ONLINE & IDLE → selecting self-hosted."
  emit "$SELF_JSON" "$LABEL" "true" "online-idle"
  summary "### Runner selection — home (fast path)

- **Selected:** \`$SELF_JSON\` — 🟢 \`$R_NAME\` is **online** and **idle**
- **Home pool:** ${R_IDLE} idle / ${R_ONLINE} online / ${R_TOTAL} registered
- **Fallback would have been:** \`$FALLBACK\`
- **Specs:** 16 vCPU (i7-10700K) / 46 GiB / NVMe — expect 3-6× vs 2 vCPU GH
- **Reason:** probe succeeded in <${TIMEOUT_SECS}s
"
  exit 0
fi

# Online but every instance is busy: QUEUE on the box rather than fall back.
# Measured 2026-08-28: a lane that fell back to ubuntu-latest spent 357-422 s
# in environment setup alone (cold uv sync, service containers, model
# download) — longer than any realistic wait for a home slot, where the same
# setup is 13 s. Fallback is for offline/unreachable, not for "busy".
if [[ "$R_STATUS" == "online" ]]; then
  SELF_JSON='["self-hosted","'"$LABEL"'"]'
  log "Home pool online but all ${R_ONLINE} instance(s) busy → queueing on self-hosted (setup there is ~30x cheaper than GitHub's)."
  emit "$SELF_JSON" "$LABEL" "true" "online-busy-queued"
  summary "### Runner selection — home (queued)

- **Selected:** \`$SELF_JSON\` — 🟡 all ${R_ONLINE} online instance(s) busy; job queues for the next free slot
- **Home pool:** ${R_IDLE} idle / ${R_ONLINE} online / ${R_TOTAL} registered
- **Why not fall back:** GitHub-hosted env setup measured at 357-422 s vs 13 s on the box
"
  exit 0
fi

# Runner registered but offline
REASON="offline (${R_ONLINE}/${R_TOTAL} online)"

log "Home runner not schedulable: $REASON. Falling back to $FALLBACK."
if [[ "$FORCE" == "true" ]]; then
  echo "::error::Home runner $REASON but FORCE_HOME=true"
  exit 1
fi
emit "$FALLBACK" "$FALLBACK_LABEL" "false" "$REASON"
summary "### Runner selection — fallback (home not schedulable)

- **Selected:** \`$FALLBACK\`
- **Home pool:** ${R_IDLE} idle / ${R_ONLINE} online / ${R_TOTAL} registered — **$REASON**
- **Home labels:** \`$R_LABELS\`
- **Fallback:** \`$FALLBACK\`
"
