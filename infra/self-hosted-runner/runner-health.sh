#!/usr/bin/env bash
# runner-health.sh — restart listeners that GitHub considers offline.
#
# Measured 2026-08-29: after a broker-side socket reset every one of the 20
# listeners kept its process, its systemd unit (active/running) and an idle
# TCP socket, but never re-created its session — GitHub listed the whole pool
# `offline` for 30+ minutes and every push fell back to GitHub-hosted runners.
# `systemctl is-active` cannot see this; only the runners API can. A restart
# re-creates the session in seconds.
#
# Rules: only a runner whose API status is `offline` AND whose unit is active
# AND that has no Runner.Worker (no job in flight) AND whose listener has not
# (re)created its session in the last RESTART_GRACE_MIN minutes is restarted.
# The grace period keeps a GitHub-side status lag (sessions created, API still
# says offline for minutes) from turning into a restart loop. A busy or
# healthy runner is never touched. Needs a gh login on the box (repo scope).
#
# Env: RUNNER_REPO (owner/repo, default theexperiencecompany/gaia),
#      RUNNER_NAME_PREFIX (default gaia-home-), RESTART_GRACE_MIN (default 15).
set -euo pipefail

REPO="${RUNNER_REPO:-theexperiencecompany/gaia}"
PREFIX="${RUNNER_NAME_PREFIX:-gaia-home-}"
GRACE_MIN="${RESTART_GRACE_MIN:-15}"

# Minutes since this runner's listener last created a broker session.
session_age_min() {
  local log
  log="$(ls -t "$HOME/actions-runner-$1/_diag"/Runner_*.log 2>/dev/null | head -n 1)" || return 1
  [[ -n "$log" ]] || return 1
  local stamp
  stamp="$(grep -E 'Session created\.' "$log" | tail -n 1 | sed -E 's/^\[([0-9-]+ [0-9:]+)Z.*/\1/')"
  [[ -n "$stamp" ]] || return 1
  echo $(( ( $(date -u +%s) - $(date -u -d "$stamp" +%s) ) / 60 ))
}

offline="$(gh api "repos/${REPO}/actions/runners" --paginate \
  --jq '.runners[] | select(.status == "offline") | .name')" || {
  echo "runner-health: runners API unreachable — nothing done"
  exit 0
}
[[ -n "$offline" ]] || { echo "runner-health: every runner online"; exit 0; }

restarted=0
while read -r name; do
  [[ "$name" == "$PREFIX"* ]] || continue
  idx="${name#"$PREFIX"}"
  unit="gaia-runner@${idx}.service"
  systemctl --user is-active --quiet "$unit" || { echo "runner-health: $name offline and $unit inactive — leaving it"; continue; }
  if pgrep -f "actions-runner-${name}/bin/Runner.Worker" >/dev/null; then
    echo "runner-health: $name offline per API but a job is running — leaving it"
    continue
  fi
  if age="$(session_age_min "$name")" && (( age < GRACE_MIN )); then
    echo "runner-health: $name offline per API but its session is ${age} min old (grace ${GRACE_MIN}) — leaving it"
    continue
  fi
  echo "runner-health: $name offline with an active listener and no job — restarting $unit"
  systemctl --user restart "$unit"
  restarted=$((restarted + 1))
done <<< "$offline"
echo "runner-health: restarted ${restarted} listener(s)"
