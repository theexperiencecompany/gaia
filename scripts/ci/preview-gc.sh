#!/usr/bin/env bash
# preview-gc.sh — garbage-collect leftovers from gaia-previewctl PR previews.
#
# previewctl (github.com/theexperiencecompany/gaia-previewctl, deployed on
# gaia-home-server as user `gaia`) creates a per-PR git worktree, a generated
# env file, a rendered compose dir, a Traefik dynamic route and a docker
# compose project `gaia-pr-{N}` for every PR labeled `staging`. Its teardown
# path removes the docker objects but routinely leaves the on-disk artifacts
# behind (~130 MB per PR in worktrees alone).
#
# This script removes the leftovers for previews whose PR is closed/merged, or
# that are older than --days N (default 7). Dry-run by default; --apply acts.
#
# Usage (on the box, as user gaia):
#   bash preview-gc.sh                 # dry run, closed/merged + >7d
#   bash preview-gc.sh --apply         # act
#   bash preview-gc.sh --closed-only --apply
#   bash preview-gc.sh --days 14
set -uo pipefail

WORKSPACE="${PREVIEW_GC_WORKSPACE:-/home/gaia/gaia-staging}"
RUNTIME_DIR="$WORKSPACE/.previewctl/runtime/gaia"
WORKTREES="$RUNTIME_DIR/worktrees"
GENERATED_ENV="$RUNTIME_DIR/generated-env"
INFRA="$WORKSPACE/staging-infra"
APP_REPO="$WORKSPACE/gaia"
REPO_SLUG="${PREVIEW_GC_REPO:-theexperiencecompany/gaia}"
# PR 0 == the always-on `develop` preview. Never a GC candidate.
KEEP_PRS=(0)

APPLY=0
DAYS=7
CLOSED_ONLY=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply) APPLY=1 ;;
    --days) DAYS="$2"; shift ;;
    --closed-only) CLOSED_ONLY=1 ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
  shift
done

log() { printf '%s\n' "$*"; }
act() {
  if [[ $APPLY -eq 1 ]]; then
    log "  REMOVE  $*"
    return 0
  fi
  log "  would remove  $*"
  return 1
}

# --- discover previews on disk -------------------------------------------
declare -A SEEN=()
add() { [[ -n "${1:-}" ]] && SEEN["$1"]=1; }
for d in "$WORKTREES"/pr-*; do [[ -d "$d" ]] && add "${d##*/pr-}"; done
for f in "$GENERATED_ENV"/pr-*.env; do
  [[ -f "$f" ]] || continue; n="${f##*/pr-}"; add "${n%.env}"
done
for d in "$INFRA"/deploy/pr-*; do [[ -d "$d" ]] && add "${d##*/pr-}"; done

# --- open PRs -------------------------------------------------------------
OPEN=""
if command -v gh >/dev/null 2>&1; then
  OPEN=$(gh pr list --repo "$REPO_SLUG" --state open --limit 300 \
           --json number --jq '.[].number' 2>/dev/null)
fi
if [[ -z "$OPEN" ]]; then
  echo "ERROR: could not list open PRs via gh; refusing to GC blind." >&2
  exit 1
fi
is_open() { grep -qx "$1" <<<"$OPEN"; }

DOCKER_HOST="${DOCKER_HOST:-unix:///run/user/$(id -u)/docker.sock}"
export DOCKER_HOST

now=$(date +%s)
reclaim_kb=0
removed=()
kept=()

for pr in $(printf '%s\n' "${!SEEN[@]}" | sort -n); do
  [[ "$pr" =~ ^[0-9]+$ ]] || { kept+=("pr-$pr (non-numeric, skipped)"); continue; }
  skip=0
  for k in "${KEEP_PRS[@]}"; do [[ "$pr" == "$k" ]] && skip=1; done
  [[ $skip -eq 1 ]] && { kept+=("pr-$pr (protected)"); continue; }

  wt="$WORKTREES/pr-$pr"
  age_days=0
  if [[ -d "$wt" ]]; then
    age_days=$(( (now - $(stat -c %Y "$wt")) / 86400 ))
  fi

  reason=""
  if is_open "$pr"; then
    if [[ $CLOSED_ONLY -eq 0 && $age_days -gt $DAYS ]]; then
      reason="open PR but stale (${age_days}d > ${DAYS}d)"
    else
      kept+=("pr-$pr (PR open, ${age_days}d)")
      continue
    fi
  else
    reason="PR closed/merged"
  fi

  size_kb=0
  [[ -d "$wt" ]] && size_kb=$(du -sk "$wt" 2>/dev/null | cut -f1)
  log "pr-$pr  — $reason  ($(( size_kb / 1024 )) MB, ${age_days}d)"

  # docker compose project gaia-pr-N: containers, then its volumes/images
  proj="gaia-pr-$pr"
  cids=$(docker ps -aq --filter "label=com.docker.compose.project=$proj" 2>/dev/null)
  if [[ -n "$cids" ]]; then
    act "containers ($proj): $(tr '\n' ' ' <<<"$cids")" && docker rm -f $cids >/dev/null
  fi
  vols=$(docker volume ls -q --filter "label=com.docker.compose.project=$proj" 2>/dev/null)
  if [[ -n "$vols" ]]; then
    act "volumes: $(tr '\n' ' ' <<<"$vols")" && docker volume rm $vols >/dev/null
  fi
  imgs=$(docker images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null \
           | grep -E "^gaia-staging/(api|web):pr-$pr-" || true)
  if [[ -n "$imgs" ]]; then
    act "images: $(tr '\n' ' ' <<<"$imgs")" && docker rmi -f $imgs >/dev/null
  fi

  # git worktree (remove via git so .git/worktrees metadata goes too)
  if [[ -d "$wt" ]]; then
    act "worktree $wt" && {
      git -C "$APP_REPO" worktree remove --force "$wt" 2>/dev/null || rm -rf "$wt"
    }
  fi

  # rendered compose dir, generated env, per-PR postgres env, Traefik route
  for p in "$INFRA/deploy/pr-$pr" "$GENERATED_ENV/pr-$pr.env" \
           "$INFRA/env/postgres/pr-$pr.env" "$INFRA/traefik/dynamic/pr-$pr.yml"; do
    [[ -e "$p" ]] && { act "$p" && rm -rf "$p"; }
  done

  reclaim_kb=$(( reclaim_kb + size_kb ))
  removed+=("pr-$pr")
done

if [[ $APPLY -eq 1 ]]; then
  git -C "$APP_REPO" worktree prune >/dev/null 2>&1
fi

log ""
log "previews GC'd: ${#removed[@]}  [${removed[*]:-none}]"
log "worktree disk $( [[ $APPLY -eq 1 ]] && echo reclaimed || echo reclaimable ): $(( reclaim_kb / 1024 )) MB"
log "kept: ${#kept[@]}"
for k in "${kept[@]}"; do log "  $k"; done
[[ $APPLY -eq 0 ]] && log "" && log "(dry run — pass --apply to act)"
exit 0
