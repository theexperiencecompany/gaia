#!/usr/bin/env bash
# runner.sh — everything about WHERE and HOW HARD a CI job runs.
#
# Subcommands:
#   select              Decide home self-hosted vs GitHub-hosted, with total
#                       fallback. Writes runner/runner_label/is_self_hosted/
#                       reason to $GITHUB_OUTPUT (stdout when unset).
#   watchdog            Cancel this run once any job has stayed `queued` past
#                       the limit — a box that died after `select` decided.
#   cancel-superseded   Cancel older queued/in-progress runs of this workflow
#                       on this branch (per-SHA concurrency needs it).
#   prime-archive [dir] Pre-populate the runner's action archive cache with
#                       every SHA-pinned `uses:` in .github.
#   parallel [flag]     Emit parallelism sized from this runner's CPU/RAM.
#                       Flags: --nx --pytest --pytest-n --ruff --mypy --docker
#                       --env (default) --json.
#   dep-marker <kind>   Print the marker path that decides whether a persisted
#                       node|python install is stale.
#   with-slots N -- cmd Acquire N host CPU tokens (lib/cpu-slots.sh), run cmd,
#                       release them. For a lane whose heavy command is not its
#                       own script — the nx build step passes NX_PARALLEL — so a
#                       workflow step stays one command line.
#
# Env contract:
#   select             GITHUB_TOKEN (repo scope), GITHUB_REPOSITORY,
#                      RUNNER_LABEL (default gaia-home), FALLBACK_RUNNER
#                      (default ["ubuntu-latest"]), FORCE_HOME, FORCE_GITHUB,
#                      PR_HEAD_REPO, PR_AUTHOR_ASSOCIATION, GITHUB_ACTOR;
#                      writes $GITHUB_OUTPUT and $GITHUB_STEP_SUMMARY.
#   watchdog           GITHUB_TOKEN (actions: write), GITHUB_REPOSITORY,
#                      GITHUB_RUN_ID, WATCHDOG_JOB_NAME (required),
#                      QUEUE_LIMIT_SECS (480), POLL_SECS (30).
#   cancel-superseded  GITHUB_TOKEN (actions: write), GITHUB_REPOSITORY,
#                      GITHUB_RUN_ID, GITHUB_WORKFLOW_REF, GITHUB_HEAD_REF or
#                      GITHUB_REF_NAME, GITHUB_EVENT_NAME.
#   prime-archive      gh auth; ACTIONS_RUNNER_ACTION_ARCHIVE_CACHE, GAIA_REPO
#                      (checkout to scan when run from a copy outside the repo).
#   parallel           PYTEST_WORKER_GB (1.5) — per-xdist-worker RAM budget.
set -euo pipefail

# shellcheck source=scripts/ci/lib/log.sh
source "$(dirname "$0")/lib/log.sh"
# shellcheck source=scripts/ci/lib/cpu-slots.sh
source "$(dirname "$0")/lib/cpu-slots.sh"

# ── select ────────────────────────────────────────────────────────────────
# Elegant fallback contract:
#   * Runs entirely on ubuntu-latest (no Tailscale needed from GH side).
#   * Probes GitHub Actions API for runner liveness — no inbound ports, no SSH.
#   * Timeout + retry so a flaky API never blocks the lane.
#   * Downstream jobs use  runs-on: ${{ fromJSON(needs.select-runner.outputs.runner) }}
#   * Fallback is total: never leaves a job queued on an offline self-hosted label.
cmd_select() {
  local LABEL DEFAULT_FALLBACK FALLBACK REPO TOKEN FORCE FORCE_GH
  local HEAD_REPO AUTHOR_ASSOC ACTOR API FALLBACK_LABEL

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

  # Fork PRs never touch the box. The runner user's workspace, caches and network
  # are shared state, and this is a public repo: code from outside it runs only on
  # GitHub's throwaway VMs. Decided before the probe on purpose — a fork's token
  # happens to be unable to list runners today, but that is an accident of token
  # scopes, not a policy.
  if [[ -n "$HEAD_REPO" && "$HEAD_REPO" != "$REPO" ]]; then
    _select_log "PR head is $HEAD_REPO (fork of $REPO) — fork code never runs on the home box."
    _select_emit "$FALLBACK" "$FALLBACK_LABEL" "false" "fork"
    _select_summary "### Runner selection — fallback (fork)

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
    _select_log "PR author association is $AUTHOR_ASSOC (not OWNER/MEMBER) — only organisation members run on the home box."
    _select_emit "$FALLBACK" "$FALLBACK_LABEL" "false" "untrusted-author"
    _select_summary "### Runner selection — fallback (author not an organisation member)

- **Selected:** \`$FALLBACK\` — PR author association is \`$AUTHOR_ASSOC\`; only OWNER/MEMBER run on the home box
"
    exit 0
  fi

  # Bots (Dependabot, release bots) run code nobody reviewed before CI: their
  # dependency bumps execute postinstall scripts. GitHub's throwaway VMs only.
  if [[ "$ACTOR" == *"[bot]" ]]; then
    _select_log "Actor $ACTOR is a bot — bots never run on the home box."
    _select_emit "$FALLBACK" "$FALLBACK_LABEL" "false" "bot-actor"
    _select_summary "### Runner selection — fallback (bot actor)

- **Selected:** \`$FALLBACK\` — actor \`$ACTOR\` is a bot; bots never run on the home box
"
    exit 0
  fi

  # Exercise the GitHub-hosted path on demand (workflow_dispatch force_github):
  # the fallback only proves itself when it actually runs.
  if [[ "$FORCE_GH" == "true" ]]; then
    _select_log "FORCE_GITHUB=true — selecting $FALLBACK without probing."
    _select_emit "$FALLBACK" "$FALLBACK_LABEL" "false" "forced-github"
    _select_summary "### Runner selection — fallback (forced)

- **Selected:** \`$FALLBACK\` — \`force_github\` set on this dispatch
"
    exit 0
  fi

  if [[ -z "$TOKEN" ]]; then
    _select_log "No GITHUB_TOKEN — cannot probe API. Falling back to $FALLBACK (local run)."
    _select_emit "$FALLBACK" "$FALLBACK_LABEL" "false" "no-token"
    _select_summary "### Runner selection — fallback (no token)

- **Selected:** \`$FALLBACK\` (no API token available)
- **Home label probed:** \`$LABEL\`
- **Reason:** local execution without GITHUB_TOKEN
"
    exit 0
  fi

  # Probe GitHub API with retries and hard timeout.
  # We call /actions/runners once, then filter locally with jq/python.
  local ATTEMPTS=3 TIMEOUT_SECS=10 API_JSON="" api_ok=false i

  for i in $(seq 1 $ATTEMPTS); do
    _select_log "Probing $API (attempt $i/$ATTEMPTS, ${TIMEOUT_SECS}s timeout)..."
    # --max-time caps total, --connect-timeout caps TCP handshake
    if API_JSON=$(curl -sSf --max-time "$TIMEOUT_SECS" --connect-timeout 5 \
         -H "Authorization: Bearer $TOKEN" \
         -H "Accept: application/vnd.github+json" \
         -H "X-GitHub-Api-Version: 2022-11-28" \
         "$API" 2>&1); then
      api_ok=true
      break
    else
      _select_log "Attempt $i failed: ${API_JSON:0:300}"
      API_JSON=""
      if (( i < ATTEMPTS )); then
        sleep $((i * 2))
      fi
    fi
  done

  if [[ "$api_ok" != "true" ]]; then
    _select_log "API unavailable after $ATTEMPTS attempts. Falling back."
    if [[ "$FORCE" == "true" ]]; then
      ci_die "HOME runner forced but API probe failed"
    fi
    _select_emit "$FALLBACK" "$FALLBACK_LABEL" "false" "api-unavailable"
    _select_summary "### Runner selection — fallback (API unavailable)

- **Selected:** \`$FALLBACK\`
- **Home label:** \`$LABEL\`
- **Reason:** GitHub API unreachable after ${ATTEMPTS} attempts (${TIMEOUT_SECS}s each)
- **Fallback after:** ~$((ATTEMPTS * (TIMEOUT_SECS + 2)))s worst case
"
    exit 0
  fi

  local RUNNER_LINE
  RUNNER_LINE="$(_select_parse_runner "$API_JSON" "$LABEL" || true)"

  if [[ -z "$RUNNER_LINE" ]]; then
    _select_log "No runner matching label '$LABEL' registered. Fallback."
    if [[ "$FORCE" == "true" ]]; then
      ci_die "No runner with label $LABEL"
    fi
    _select_emit "$FALLBACK" "$FALLBACK_LABEL" "false" "not-registered"
    _select_summary "### Runner selection — fallback (not registered)

- **Selected:** \`$FALLBACK\`
- **Home label:** \`$LABEL\`
- **Reason:** no runner with label \`$LABEL\` found (register via self-hosted-runner/setup.sh in the private gaia-infra repo)
"
    exit 0
  fi

  local R_NAME R_STATUS R_BUSY R_OS R_LABELS R_ONLINE R_IDLE R_TOTAL SELF_JSON REASON
  IFS='|' read -r R_NAME R_STATUS R_BUSY R_OS R_LABELS R_ONLINE R_IDLE R_TOTAL <<< "$RUNNER_LINE"
  _select_log "Home pool '$LABEL': ${R_IDLE} idle / ${R_ONLINE} online / ${R_TOTAL} registered — picked $R_NAME (status=$R_STATUS busy=$R_BUSY os=$R_OS)"

  if [[ "$R_STATUS" == "online" && "$R_BUSY" == "false" ]]; then
    SELF_JSON='["self-hosted","'"$LABEL"'"]'
    _select_log "Home runner ONLINE & IDLE → selecting self-hosted."
    _select_emit "$SELF_JSON" "$LABEL" "true" "online-idle"
    _select_summary "### Runner selection — home (fast path)

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
    _select_log "Home pool online but all ${R_ONLINE} instance(s) busy → queueing on self-hosted (setup there is ~30x cheaper than GitHub's)."
    _select_emit "$SELF_JSON" "$LABEL" "true" "online-busy-queued"
    _select_summary "### Runner selection — home (queued)

- **Selected:** \`$SELF_JSON\` — 🟡 all ${R_ONLINE} online instance(s) busy; job queues for the next free slot
- **Home pool:** ${R_IDLE} idle / ${R_ONLINE} online / ${R_TOTAL} registered
- **Why not fall back:** GitHub-hosted env setup measured at 357-422 s vs 13 s on the box
"
    exit 0
  fi

  # Runner registered but offline
  REASON="offline (${R_ONLINE}/${R_TOTAL} online)"

  _select_log "Home runner not schedulable: $REASON. Falling back to $FALLBACK."
  if [[ "$FORCE" == "true" ]]; then
    ci_die "Home runner $REASON but FORCE_HOME=true"
  fi
  _select_emit "$FALLBACK" "$FALLBACK_LABEL" "false" "$REASON"
  _select_summary "### Runner selection — fallback (home not schedulable)

- **Selected:** \`$FALLBACK\`
- **Home pool:** ${R_IDLE} idle / ${R_ONLINE} online / ${R_TOTAL} registered — **$REASON**
- **Home labels:** \`$R_LABELS\`
- **Fallback:** \`$FALLBACK\`
"
}

_select_log() { echo "[select-runner] $*" >&2; }

_select_emit() {
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

_select_summary() {
  local msg="$1"
  if [[ -n "${GITHUB_STEP_SUMMARY:-}" && -f "${GITHUB_STEP_SUMMARY:-}" ]]; then
    echo "$msg" >> "$GITHUB_STEP_SUMMARY"
  fi
  # Always log to stderr so it appears in job log
  _select_log "$msg"
}

# Parse runners JSON. Prefer jq, fallback to python3.
#
# The home box runs several runner instances, all carrying the same label, so
# "is home usable?" is a question about the POOL, not about one instance:
# pick the first instance that is online AND idle. Selecting on the first
# matching instance regardless of state would fall back to GitHub whenever
# instance 1 happened to be busy, even with three others sitting idle.
#
# Emits: "<name>|<status>|<busy>|<os>|<labels>|<online_count>|<idle_count>|<total>"
_select_parse_runner() {
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

# ── watchdog ──────────────────────────────────────────────────────────────
# `select` decides once, at the start of the run. If the box dies between that
# decision and pickup (reboot, uplink drop, runner units stopped), GitHub keeps
# the self-hosted jobs `queued` for up to 24 h — timeout-minutes only starts
# once a job is picked up — and the PR check sits pending all day.
#
# Runs on ubuntu-latest alongside the compute lanes: polls this run's jobs and,
# when any job has been queued past QUEUE_LIMIT_SECS *with the run making no
# progress and no home runner online*, cancels the run with an error that says
# what to do (re-run with force_github=true).
#
# Two false positives this deliberately does NOT trip on:
#   * An empty job list. A job whose `needs:` are unmet has no record yet, so
#     the first poll of a run often lists nothing but this watchdog. Exiting
#     there (the old behaviour) meant the watchdog was gone before the lanes
#     it watches existed. It now keeps polling until the run leaves
#     in_progress or every job it can see is in_progress/terminal.
#   * A job queued on purpose. `select`'s online-busy-queued branch parks lanes
#     on a busy box because the box's setup is ~30x cheaper than GitHub's, and
#     a full box can exceed the limit honestly. So age is measured from when
#     the job became ELIGIBLE — the later of its creation and the run's last
#     sign of progress — and before cancelling the runners API is re-probed:
#     if any instance carrying the label is online, the queue is real work,
#     not a dead box. An inconclusive probe never cancels; the watchdog's own
#     timeout-minutes bounds it instead.
cmd_watchdog() {
  local LIMIT POLL API LABEL run_status jobs queued live now last_progress
  local name _status created started completed eligible age stalled probe
  local stamp online_rc
  LIMIT="${QUEUE_LIMIT_SECS:-480}"
  POLL="${POLL_SECS:-30}"
  LABEL="${RUNNER_LABEL:-gaia-home}"
  : "${WATCHDOG_JOB_NAME:?WATCHDOG_JOB_NAME is required}"
  export WATCHDOG_JOB_NAME
  API="repos/${GITHUB_REPOSITORY}/actions/runs/${GITHUB_RUN_ID}"

  while :; do
    run_status="$(gh api "$API" --jq '.status')"
    case "$run_status" in
      queued|pending|waiting|in_progress) ;;
      *)
        ci_ok "watchdog: run is ${run_status} — nothing left to watch"
        exit 0
        ;;
    esac

    # name<TAB>status<TAB>created_at<TAB>started_at<TAB>completed_at, one job
    # per line, this watchdog excluded.
    jobs="$(gh api "${API}/jobs?per_page=100" \
      --jq '.jobs[] | select(.name != env.WATCHDOG_JOB_NAME)
            | [.name, .status, (.created_at // ""), (.started_at // ""), (.completed_at // "")] | @tsv')"
    queued="$(printf '%s\n' "$jobs" | awk -F'\t' '$2 == "queued"')"
    live="$(printf '%s\n' "$jobs" | awk -F'\t' 'NF && $2 != "completed"')"

    if [[ -z "$queued" ]]; then
      if [[ -z "$live" && -n "${jobs//[[:space:]]/}" ]]; then
        ci_ok "watchdog: every lane finished"
        exit 0
      fi
      if [[ -n "${jobs//[[:space:]]/}" ]]; then
        ci_ok "watchdog: no queued jobs — every lane was picked up"
        exit 0
      fi
      # No jobs yet: their `needs:` have not resolved. Keep watching.
      echo "watchdog: no lanes created yet (run ${run_status}) — waiting"
      sleep "$POLL"
      continue
    fi

    now="$(date -u +%s)"
    # The run's last sign of progress: the newest moment any lane started or
    # finished. A lane that only just became eligible has not been stalled for
    # however long its record has existed.
    last_progress=0
    while IFS=$'\t' read -r name _status created started completed; do
      [[ -n "$name" ]] || continue
      for stamp in "$started" "$completed"; do
        [[ -n "$stamp" ]] || continue
        probe="$(_epoch "$stamp")"
        (( probe > last_progress )) && last_progress="$probe"
      done
    done <<< "$jobs"

    stalled=""
    while IFS=$'\t' read -r name _status created started completed; do
      [[ -n "$name" ]] || continue
      eligible="$(_epoch "$created")"
      (( last_progress > eligible )) && eligible="$last_progress"
      age=$(( now - eligible ))
      echo "watchdog: '$name' eligible for ${age}s (limit ${LIMIT}s)"
      (( age > LIMIT )) && stalled="$name"
    done <<< "$queued"

    if [[ -n "$stalled" ]]; then
      _watchdog_home_online "$LABEL" && online_rc=0 || online_rc=$?
      case "$online_rc" in
        0) ci_warn "'$stalled' has been queued for over ${LIMIT}s, but instances labelled '${LABEL}' are online — the box is busy, not dead. Not cancelling." ;;
        2) ci_warn "'$stalled' has been queued for over ${LIMIT}s and the runners API could not be probed — not cancelling on an unknown." ;;
        *)
          echo "::error::'$stalled' has been queued past ${LIMIT}s and no runner labelled '${LABEL}' is online — the home runner accepted the run but is not picking jobs up. Cancelling; re-run with force_github=true to use GitHub-hosted runners."
          gh api -X POST "${API}/cancel" >/dev/null
          exit 1
          ;;
      esac
    fi
    sleep "$POLL"
  done
}

# 0 = at least one instance with this label is online, 1 = none is,
# 2 = the API could not be read (never a reason to cancel a run).
_watchdog_home_online() {
  local label="$1" n
  n="$(gh api "repos/${GITHUB_REPOSITORY}/actions/runners" --paginate \
        --jq "[.runners[]? | select(any(.labels[]?; .name == \"${label}\")) | select(.status == \"online\")] | length" \
        2>/dev/null || true)"
  [[ -n "$n" ]] || return 2
  # --paginate concatenates one count per page.
  n="$(printf '%s\n' "$n" | awk '{s += $1} END {print s + 0}')"
  (( n > 0 ))
}

# ISO-8601 (…Z) → epoch seconds. GNU `date -u -d` is not portable to the dev
# laptop, and the watchdog's decision logic has to be testable there.
_epoch() {
  [[ -n "$1" ]] || { echo 0; return 0; }
  python3 -c 'import sys,datetime
print(int(datetime.datetime.fromisoformat(sys.argv[1].replace("Z","+00:00")).timestamp()))' "$1"
}

# ── cancel-superseded ─────────────────────────────────────────────────────
# Why not `concurrency.cancel-in-progress`: with a shared group the NEW run sits
# in "pending" until the OLD run's cancellation completes. On the self-hosted
# box a cancelled pytest step wedges the runner worker until the listener's
# 5-minute cancellation timeout (measured three times on 2026-08-28), so every
# push cost the next run 5 minutes before its first job started. The workflows
# now use a per-SHA concurrency group and this step cancels the superseded runs
# asynchronously: the new run starts at once, the old one dies on its own time.
# Runs on master coalesce the same way ("final verification wins").
cmd_cancel_superseded() {
  local workflow_file branch event older id
  workflow_file="$(echo "${GITHUB_WORKFLOW_REF}" | sed -E 's#.*/\.github/workflows/([^@]+)@.*#\1#')"
  branch="${GITHUB_HEAD_REF:-${GITHUB_REF_NAME}}"
  event="${GITHUB_EVENT_NAME:-}"

  older="$(gh api --paginate \
    "repos/${GITHUB_REPOSITORY}/actions/workflows/${workflow_file}/runs?branch=${branch}&event=${event}&per_page=50" \
    --jq ".workflow_runs[] | select(.id < ${GITHUB_RUN_ID}) | select(.status == \"queued\" or .status == \"in_progress\" or .status == \"waiting\" or .status == \"pending\") | .id")"

  if [ -z "$older" ]; then
    ci_ok "no superseded ${workflow_file} runs on ${branch}"
    exit 0
  fi
  for id in $older; do
    if gh api -X POST "repos/${GITHUB_REPOSITORY}/actions/runs/${id}/cancel" > /dev/null 2>&1; then
      echo "cancelled superseded run ${id}"
    else
      ci_warn "could not cancel run ${id} (already finishing?)"
    fi
  done
}

# ── prime-archive ─────────────────────────────────────────────────────────
# The runner only READS $ACTIONS_RUNNER_ACTION_ARCHIVE_CACHE (Runner.Worker
# ActionManager.cs: "<cache>/<owner>_<repo>/<sha>.tar.gz"); it never writes to
# it. With the directory empty every job spent ~20 s re-downloading the same
# pinned action tarballs from codeload (measured 2026-08-28: five actions,
# 01:29:50→01:30:09 on one job). This fetches every SHA-pinned `uses:` in the
# repo's workflows and composites once; re-run after bumping a pin (setup.sh
# and the nightly prune timer both call it).
cmd_prime_archive() {
  local CACHE REPO_ROOT fetched present ref slug want repo sha dir file
  CACHE="${1:-${ACTIONS_RUNNER_ACTION_ARCHIVE_CACHE:-$HOME/ci-cache/actions-archive}}"
  REPO_ROOT="${GAIA_REPO:-$(cd "$(dirname "$0")/../.." && pwd)}"
  [ -d "$REPO_ROOT/.github" ] || ci_die "no workflows under $REPO_ROOT (set GAIA_REPO)"
  mkdir -p "$CACHE"

  fetched=0 present=0
  while IFS= read -r ref; do
    slug="${ref%@*}"; want="${ref#*@}"
    # Nested paths (owner/repo/sub@sha) resolve to the repo's tarball.
    repo="$(echo "$slug" | cut -d/ -f1-2)"
    # The runner keys the archive by the RESOLVED commit, so a tag or branch
    # ref (`actions/checkout@v7`) has to be resolved the same way it will be at
    # job time; a moved tag simply primes a new entry next run.
    if [[ "$want" =~ ^[0-9a-f]{40}$ ]]; then
      sha="$want"
    else
      sha="$(gh api "repos/$repo/commits/$want" --jq .sha 2>/dev/null || true)"
      [ -n "$sha" ] || { ci_warn "could not resolve $repo@$want"; continue; }
    fi
    dir="$CACHE/${repo//\//_}"
    file="$dir/$sha.tar.gz"
    if [ -s "$file" ]; then present=$((present + 1)); continue; fi
    mkdir -p "$dir"
    if gh api "repos/$repo/tarball/$sha" > "$file.part" 2>/dev/null && [ -s "$file.part" ]; then
      mv -f "$file.part" "$file"; fetched=$((fetched + 1)); echo "fetched $repo@$sha"
    else
      rm -f "$file.part"; ci_warn "could not fetch $repo@$sha"
    fi
  done < <(grep -rhoE '^\s*-?\s*uses:\s*[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+@[A-Za-z0-9_./-]+' \
             "$REPO_ROOT/.github" | sed -E 's/^.*uses:\s*//' | sort -u)

  ci_ok "action archive: $present present, $fetched fetched → $CACHE"
}

# ── parallel ──────────────────────────────────────────────────────────────
# Insanely great home-server utilization:
#   16 vCPU (8c/16t i7-10700K) should run at full tilt, not at "3".
#   2 vCPU GitHub should stay conservative to avoid OOM/thrashing.
#
# To import the values into a shell or into $GITHUB_ENV:
#   eval "$(bash scripts/ci/runner.sh parallel --env)"
#   bash scripts/ci/runner.sh parallel --env >> "$GITHUB_ENV"
cmd_parallel() {
  # Names kept identical to the variables the lanes read, so the contract reads
  # the same; _parallel_emit_env sees them through bash's dynamic scoping.
  local NPROC MEM_GB NX_PARALLEL PYTEST_XDIST PYTEST_XDIST_N RUFF_JOBS MYPY_JOBS
  local DOCKER_JOBS MEM_AVAIL_GB PER_WORKER_GB HEADROOM_GB MEM_WORKERS
  local RUNNING_WORKERS CPU_WORKERS

  NPROC="$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 2)"
  MEM_GB="$(free -g 2>/dev/null | awk '/^Mem:/{print $2}' || echo 4)"

  # Heuristics tuned for GAIA workloads (measured on both 2c GH and 16c home):
  #   nx build: scales to ~8 before I/O contention; beyond that use 16 with --parallel but cap per-batch memory
  #   pytest xdist: scales to nproc, but each worker is ~2.5 GB on this suite — memory caps first
  #   ruff: scales to nproc (tiny per-file)
  #   mypy: dmypy + --jobs nproc gives ~2.5× at 16c vs 2c (still partially serial due to graph)
  #   docker buildx: can parallelize layers, but I/O bound
  if (( NPROC >= 14 )); then
    # Measured on the 16c box (benchmark run 33108678517, nx run-many -t build):
    # --parallel=2 89s, =4 42s, =8 59s. Past 4 the Next.js/tsc workers contend
    # for the same cores and memory; 6 leaves headroom for one more concurrent
    # lane on the box without regressing the build itself.
    NX_PARALLEL=6
    PYTEST_XDIST="auto"         # xdist auto == nproc (16)
    PYTEST_XDIST_N=16
    RUFF_JOBS="$NPROC"
    MYPY_JOBS="$NPROC"
    DOCKER_JOBS="$NPROC"
  elif (( NPROC >= 7 )); then
    # 8c hosts (e.g. larger GH or small home)
    NX_PARALLEL="$NPROC"
    PYTEST_XDIST="auto"
    PYTEST_XDIST_N="$NPROC"
    RUFF_JOBS="$NPROC"
    MYPY_JOBS="$NPROC"
    DOCKER_JOBS="$NPROC"
  else
    # 2-4c GitHub / local laptops
    NX_PARALLEL=3
    PYTEST_XDIST="auto"
    PYTEST_XDIST_N="$NPROC"
    RUFF_JOBS="$NPROC"
    MYPY_JOBS="$NPROC"
    DOCKER_JOBS=2
  fi

  # Memory guard, measured not assumed: a pytest-xdist worker on this suite is
  # ~2.5 GB RSS (ps on the home box, 16 workers at 2.2-2.6 GB each — the
  # earlier 600 MB figure came from /usr/bin/time, which reports the parent
  # only). Sixteen workers is ~40 GB. Budget against memory AVAILABLE right now
  # rather than total: several runner instances share this box, and two
  # test-python lanes landing together must degrade to fewer workers each
  # instead of exhausting RAM and swap (observed: 46 GB + 8 GB swap full,
  # load 42, every core busy thrashing).
  MEM_AVAIL_GB="$(free -g 2>/dev/null | awk '/^Mem:/{print $7}' || echo "$MEM_GB")"
  # 2.5 GB was the in-process-model figure; with the embedding sidecar the
  # measured peak is 1.04-1.05 GB per worker (profiling matrix, 16 and 24
  # workers). 1.5 keeps margin without cutting workers when two lanes share
  # the box. Set PYTEST_WORKER_GB=2.5 if running without the sidecar.
  PER_WORKER_GB="${PYTEST_WORKER_GB:-1.5}"
  HEADROOM_GB=4   # OS, docker, the runner agent, the coordinating pytest process
  MEM_WORKERS="$(awk -v a="$MEM_AVAIL_GB" -v w="$PER_WORKER_GB" -v h="$HEADROOM_GB" 'BEGIN{n=int((a-h)/w); if(n<1)n=1; print n}')"
  # CPU guard, also measured: with per-worker RAM down to ~1 GB the memory cap
  # stopped throttling, and two test lanes on the box each took 16 workers —
  # 32 workers on 16 threads plus a build, and the unit lane went from 110s
  # alone to 435s. Subtract the xdist workers already running on this host so
  # concurrent lanes share the cores instead of fighting for them. Floor of 4
  # keeps a lane moving even on a crowded box.
  # pgrep -c prints "0" AND exits 1 when nothing matches, so `|| echo 0` would
  # yield "0\n0"; capture, then default only when the capture is empty.
  RUNNING_WORKERS="$(pgrep -fc '\[pytest-xdist' 2>/dev/null || true)"
  RUNNING_WORKERS="${RUNNING_WORKERS:-0}"
  CPU_WORKERS=$(( NPROC - RUNNING_WORKERS ))
  (( CPU_WORKERS < 4 )) && CPU_WORKERS=4
  if (( CPU_WORKERS < PYTEST_XDIST_N )); then
    echo "detect-parallel: cpu-capped pytest workers ${PYTEST_XDIST_N} -> ${CPU_WORKERS} (${RUNNING_WORKERS} xdist workers already running on this host)" >&2
    PYTEST_XDIST_N="$CPU_WORKERS"
    PYTEST_XDIST="$CPU_WORKERS"
  fi
  if (( MEM_WORKERS < PYTEST_XDIST_N )); then
    echo "detect-parallel: memory-capped pytest workers ${PYTEST_XDIST_N} -> ${MEM_WORKERS} (${MEM_AVAIL_GB}G available, ${PER_WORKER_GB}G/worker)" >&2
    PYTEST_XDIST_N="$MEM_WORKERS"
    PYTEST_XDIST="$MEM_WORKERS"
  fi
  if (( NPROC >= 14 )) && (( MEM_GB < 12 )); then
    NX_PARALLEL=8
  fi

  case "${1:-}" in
    --nx) echo "$NX_PARALLEL" ;;
    --pytest) echo "$PYTEST_XDIST" ;;
    --pytest-n) echo "$PYTEST_XDIST_N" ;;
    --ruff) echo "$RUFF_JOBS" ;;
    --mypy) echo "$MYPY_JOBS" ;;
    --docker) echo "$DOCKER_JOBS" ;;
    --env|"") _parallel_emit_env ;;
    --json) printf '{"nproc":%d,"mem_gb":%d,"nx_parallel":%d,"pytest_xdist":"%s","pytest_xdist_n":%d,"ruff_jobs":%d,"mypy_jobs":%d,"docker_jobs":%d}\n' "$NPROC" "$MEM_GB" "$NX_PARALLEL" "$PYTEST_XDIST" "$PYTEST_XDIST_N" "$RUFF_JOBS" "$MYPY_JOBS" "$DOCKER_JOBS" ;;
    *) echo "unknown arg $1" >&2; exit 1 ;;
  esac
}

# Dynamic scoping: reads cmd_parallel's locals, so it is only ever called from
# there.
_parallel_emit_env() {
  echo "NX_PARALLEL=$NX_PARALLEL"
  echo "PYTEST_XDIST=$PYTEST_XDIST"
  echo "PYTEST_XDIST_N=$PYTEST_XDIST_N"
  echo "RUFF_JOBS=$RUFF_JOBS"
  echo "MYPY_JOBS=$MYPY_JOBS"
  echo "DOCKER_JOBS=$DOCKER_JOBS"
  echo "NPROC=$NPROC"
  echo "MEM_GB=$MEM_GB"
  echo "MEM_AVAIL_GB=$MEM_AVAIL_GB"
}

# ── dep-marker ────────────────────────────────────────────────────────────
# The one place that decides when a persisted install is stale.
#
# The self-hosted workspace keeps node_modules and .venv between jobs and skips
# the install when a marker file left by the previous install still matches.
# The marker key must cover EVERY input that changes what the install produces,
# not just the lockfile: a `node-linker` flip in .npmrc / pnpm-workspace.yaml or
# a `packageManager` bump rewrites node_modules with an unchanged lockfile, and
# a pyproject edit changes the workspace uv syncs. Used by the composites
# (setup-node-pnpm, setup-python-test-env) and by gaia-infra:self-hosted-runner/
# setup.sh's warm-up, so all three agree on what "already installed" means.
cmd_dep_marker() {
  local kind="${1:?usage: runner.sh dep-marker node|python}"
  case "$kind" in
    node)
      echo "node_modules/.gaia-installed-$(_dep_marker_key pnpm-lock.yaml pnpm-workspace.yaml .npmrc package.json)"
      ;;
    python)
      echo ".venv/.gaia-synced-$(_dep_marker_key uv.lock pyproject.toml apps/api/pyproject.toml libs/pyproject.toml .python-version)"
      ;;
    *)
      echo "runner.sh dep-marker: unknown kind '$kind' (node|python)" >&2
      exit 2
      ;;
  esac
}

_dep_marker_key() {
  # Missing optional inputs hash as empty, so adding/removing one changes the key.
  local f
  for f in "$@"; do
    if [[ -f "$f" ]]; then cat "$f"; else printf '<absent:%s>' "$f"; fi
  done | sha256sum | cut -c1-16
}

# ── with-slots ──────────────────────────────────────────────────────────────
# Take N host CPU tokens for the duration of a command, then give them back.
# The scriptless heavy lane (the nx build) uses this so its workflow step is
# still one command line; the token-owning lanes that DO have a script
# (pytest.sh slice, mutation.sh shard) acquire inline instead. Fail-open and a
# no-op off the self-hosted box — see lib/cpu-slots.sh. The command's exit code
# is propagated; cpu_slots_acquire's EXIT trap releases even if it is killed.
cmd_with_slots() {
  local n="${1:?usage: runner.sh with-slots N -- <cmd...>}"
  shift
  [ "${1:-}" = "--" ] && shift
  [ "$#" -gt 0 ] || { echo "runner.sh with-slots: no command after N" >&2; exit 2; }
  cpu_slots_acquire "$n"
  local rc=0
  "$@" || rc=$?
  cpu_slots_release "$n"
  return "$rc"
}

usage() {
  sed -n '2,36p' "$0" >&2
}

main() {
  local sub="${1:-}"
  shift || true
  case "$sub" in
    select)            cmd_select "$@" ;;
    watchdog)          cmd_watchdog "$@" ;;
    cancel-superseded) cmd_cancel_superseded "$@" ;;
    prime-archive)     cmd_prime_archive "$@" ;;
    parallel)          cmd_parallel "$@" ;;
    dep-marker)        cmd_dep_marker "$@" ;;
    with-slots)        cmd_with_slots "$@" ;;
    *)
      echo "runner.sh: unknown subcommand '${sub}'" >&2
      usage
      exit 2
      ;;
  esac
}

main "$@"
