#!/usr/bin/env bash
# prune-cache.sh — keep the home runner's persistent CI caches bounded.
#
# Moving the pnpm store, uv cache, Nx cache, Next.js cache and embedding
# models onto local disk is what made the home runner fast (they no longer
# cross the network), but "persistent" means "grows forever" unless something
# bounds it. This is that something.
#
# The rule that decides everything below: pruning must never make the NEXT
# run slower. Anything a warm workspace still references stays.
#
#   * pnpm store and uv cache are pruned only by their own tools
#     (`pnpm store prune`, `uv cache prune`), which drop exactly the entries
#     no lockfile / no environment references. They are NOT LRU-trimmed: both
#     stores are content-addressed with a handful of top-level children
#     (pnpm: files/ index/ tmp/; uv: archive-v0/ wheels-v*/ ...), so evicting
#     a "least recently used" top-level entry rips out half the store and
#     every warm node_modules / .venv on the box goes cold at once. Their
#     budgets are reported and warned about, never enforced here.
#   * Nx and Next.js caches ARE LRU-trimmed to a budget: every entry is a
#     content-addressed cache hit, and a miss costs one rebuild of that task,
#     nothing else.
#
# What it will delete, and nothing else:
#   * pnpm store entries nothing references  (pnpm store prune)
#   * uv cache entries for versions no environment uses (uv cache prune)
#   * Nx and Next.js cache entries in each instance's workspace, LRU, down to
#     their budgets
#   * /dev/shm/.mutation-* work trees older than 60 min (scripts/test/
#     mutation.sh stages them there; a SIGKILLed run orphans its tree in RAM)
#   * STOPPED containers named gaia-test-*  (the test services, by exact name)
#   * runner _diag logs beyond the newest DIAG_KEEP
#   * runner tarballs in the cache other than the versions installed
#
# What it will NEVER touch, by design:
#   * Docker volumes and images — unrelated to CI caches, and pruning them
#     takes out this host's other services.
#   * The git mirror (it is the seed for every new runner instance).
#   * The embedding models (fixed ~1.4 GB, and re-fetching them costs a
#     multi-minute download).
#   * node_modules / .venv inside the instance workspaces (that is the warm
#     state the whole box exists to keep).
#
# Usage:
#   bash prune-cache.sh              # dry run: report what WOULD go
#   bash prune-cache.sh --apply      # actually delete
#   CACHE_ROOT=... PNPM_BUDGET_GB=20 bash prune-cache.sh --apply
set -euo pipefail

CACHE_ROOT="${RUNNER_LOCAL_CACHE:-$HOME/ci-cache}"
PNPM_BUDGET_GB="${PNPM_BUDGET_GB:-24}"   # report-only, see header; the store is ~16 GB warm (2026-08-29)
UV_BUDGET_GB="${UV_BUDGET_GB:-6}"        # report-only, see header
NX_BUDGET_GB="${NX_BUDGET_GB:-4}"
NEXT_BUDGET_GB="${NEXT_BUDGET_GB:-3}"
DIAG_KEEP="${DIAG_KEEP:-20}"
DISK_HIGH_PCT="${DISK_HIGH_PCT:-85}"
# Instances of THIS user only (setup.sh names them <prefix>-<n> under
# RUNNER_INSTALL_ROOT); a trailing dash on the prefix is tolerated.
RUNNER_GLOB="${RUNNER_GLOB:-${RUNNER_INSTALL_ROOT:-$HOME}/actions-runner-${RUNNER_NAME_PREFIX:-gaia-home}-*}"
RUNNER_GLOB="${RUNNER_GLOB//--\*/-*}"
# Per-instance caches live INSIDE the persistent workspace (actions/checkout
# runs with clean: false; hooks/job-started.sh's scoped clean spares exactly
# these paths — see .github/actions/setup-node-pnpm and restore-nextjs-cache).
WORKSPACE_REL="_work/gaia/gaia"
MUTATION_STALE_MIN="${MUTATION_STALE_MIN:-60}"

APPLY=false
[[ "${1:-}" == "--apply" ]] && APPLY=true
$APPLY || echo "[prune] DRY RUN — nothing will be deleted. Pass --apply to act."

human() { numfmt --to=iec --suffix=B "${1:-0}" 2>/dev/null || echo "${1:-0}B"; }
dir_bytes() { du -sb "$1" 2>/dev/null | cut -f1 || echo 0; }

run() {
  if $APPLY; then
    "$@"
  else
    echo "        would run: $*"
  fi
}

echo "[prune] Disk before: $(df -h / | awk 'NR==2{print $3" used, "$4" free ("$5")"}')"
echo "[prune] Cache root:  $CACHE_ROOT ($(human "$(dir_bytes "$CACHE_ROOT")"))"

# --- LRU trim ---------------------------------------------------------------
# Deletes whole top-level entries of a cache dir, oldest-touched first, until
# the directory fits its budget. Whole entries (not individual files) so a
# cache entry is never left half-present, which reads as corruption to the
# tool that owns it.
#
# Only safe on caches whose top-level entries are independent, content-
# addressed hits (Nx task outputs, Next.js pack files). NEVER point it at a
# store whose top-level children are structural (pnpm store, uv cache).
#
# An optional 4th argument restricts eviction to entries whose NAME matches
# the regex (find -regex, whole path): Nx keeps its SQLite metadata and
# terminalOutputs/ beside the numeric hash directories, and those must stay.
trim_lru() {
  local dir="$1" budget_gb="$2" label="$3" name_re="${4:-.*}"
  [[ -d "$dir" ]] || return 0
  local budget=$((budget_gb * 1024 * 1024 * 1024))
  local size; size="$(dir_bytes "$dir")"
  if (( size <= budget )); then
    echo "[prune] $label: $(human "$size") / ${budget_gb}G — within budget"
    return 0
  fi
  echo "[prune] $label: $(human "$size") / ${budget_gb}G — over by $(human $((size - budget)))"
  local freed=0
  # Oldest mtime first. -maxdepth 1 keeps entries whole.
  while IFS= read -r -d '' entry; do
    (( size - freed <= budget )) && break
    local esz; esz="$(dir_bytes "$entry")"
    echo "        evict $(human "$esz")  $(basename "$entry")"
    run rm -rf "$entry"
    freed=$((freed + esz))
  done < <(find "$dir" -mindepth 1 -maxdepth 1 -regextype posix-extended -regex "${dir%/}/$name_re" -printf '%T@ %p\0' 2>/dev/null \
           | sort -zn | cut -z -d' ' -f2-)
  echo "[prune] $label: reclaimed $(human "$freed")"
}

# --- size report (no eviction) ---------------------------------------------
# For the stores that must never be trimmed here. Over budget is a warning
# for a human, not an action: the fix is a bigger disk or a lockfile diet,
# never a cache that makes the next run cold.
report_size() {
  local dir="$1" budget_gb="$2" label="$3"
  [[ -d "$dir" ]] || return 0
  local budget=$((budget_gb * 1024 * 1024 * 1024))
  local size; size="$(dir_bytes "$dir")"
  if (( size <= budget )); then
    echo "[prune] $label: $(human "$size") / ${budget_gb}G — within budget (report only)"
  else
    echo "::warning::$label is $(human "$size"), over its ${budget_gb}G budget by $(human $((size - budget))). Not trimmed on purpose (see prune-cache.sh header); grow the budget or the disk."
  fi
}

# --- tool-native pruning (safest: each tool knows what it still needs) ------
if command -v pnpm >/dev/null 2>&1; then
  echo "[prune] pnpm store prune (drops packages no lockfile references)"
  if $APPLY; then
    pnpm store prune 2>&1 | tail -3 || \
      echo "::warning::pnpm store prune failed — continuing"
  else
    echo "        would run: pnpm store prune"
  fi
fi

if command -v uv >/dev/null 2>&1; then
  echo "[prune] uv cache prune (drops unused wheels/sdists)"
  if $APPLY; then
    uv cache prune 2>&1 | tail -3 || \
      echo "::warning::uv cache prune failed — continuing"
  else
    echo "        would run: uv cache prune"
  fi
fi

# --- shared stores: report only ---------------------------------------------
report_size "$(pnpm store path 2>/dev/null || echo "$HOME/.local/share/pnpm/store/v10")" "$PNPM_BUDGET_GB" "pnpm store"
report_size "${UV_CACHE_DIR:-$HOME/.cache/uv}" "$UV_BUDGET_GB" "uv cache"

# --- size-bounded caches (content-addressed hits; a miss = one rebuild) ------
# The Nx remote cache server evicts LRU itself (NX_CACHE_MAX_BYTES); this is a
# backstop at a slightly larger budget in case the server is down.
trim_lru "${CACHE_ROOT}/nx-remote"  "${NX_REMOTE_BUDGET_GB:-9}" "nx remote cache"
# Per-instance Nx and Next.js caches live in each runner's persistent
# workspace. Nx: only the numeric hash directories are candidates; its
# SQLite files and terminalOutputs/ sit beside them and stay. Next.js: every
# top-level entry (webpack/, swc/, images/, fetch-cache/) is a self-contained
# pack cache, so whole entries are safe to drop.
for rd in $RUNNER_GLOB; do
  ws="$rd/$WORKSPACE_REL"
  [[ -d "$ws" ]] || continue
  trim_lru "$ws/.nx/cache"            "$NX_BUDGET_GB"   "nx cache ($(basename "$rd"))" '[0-9]+'
  trim_lru "$ws/apps/web/.next/cache" "$NEXT_BUDGET_GB" "next cache ($(basename "$rd"))"
done

# --- orphaned mutation work trees in RAM ------------------------------------
# scripts/test/mutation.sh copies the module under test to /dev/shm/.mutation-
# <pid> and removes it on exit; a SIGKILL (job cancel, lane timeout) leaves it
# holding RAM. Anything older than MUTATION_STALE_MIN outlived any real run.
if [[ -d /dev/shm ]]; then
  while IFS= read -r -d '' m; do
    echo "[prune] orphaned mutation tree: $m ($(human "$(dir_bytes "$m")"))"
    run rm -rf "$m"
  done < <(find /dev/shm -mindepth 1 -maxdepth 1 -name '.mutation-*' -mmin "+${MUTATION_STALE_MIN}" -print0 2>/dev/null)
fi

# --- stopped test-service containers, by exact name pattern -----------------
# Only containers this repo's CI creates, and only ones that already exited.
# A running container is never touched: it may belong to a live job.
if command -v docker >/dev/null 2>&1; then
  STOPPED="$(docker ps -a --filter 'name=^gaia-test-' --filter 'status=exited' \
             --filter 'status=created' --format '{{.Names}}' 2>/dev/null || true)"
  if [[ -n "$STOPPED" ]]; then
    echo "[prune] stopped gaia-test-* containers:"
    echo "$STOPPED" | sed 's/^/        /'
    # shellcheck disable=SC2086
    run docker rm -f $STOPPED
  else
    echo "[prune] no stopped gaia-test-* containers"
  fi
  echo "[prune] (docker images and volumes deliberately untouched)"
fi

# --- runner diagnostics + stale tarballs ------------------------------------
for rd in $RUNNER_GLOB; do
  diag="$rd/_diag"
  [[ -d "$diag" ]] || continue
  old="$(find "$diag" -maxdepth 1 -type f -name '*.log' -printf '%T@ %p\n' 2>/dev/null \
         | sort -rn | tail -n +$((DIAG_KEEP + 1)) | cut -d' ' -f2-)"
  if [[ -n "$old" ]]; then
    echo "[prune] $(basename "$rd")/_diag: $(echo "$old" | wc -l) log(s) beyond newest ${DIAG_KEEP}"
    # shellcheck disable=SC2086
    run rm -f $old
  fi
done

# The version in use is read from the installed runners themselves, never
# from a constant here: a pin bump in setup.sh must not turn this into the
# script that deletes the tarball setup.sh is about to extract. A tarball is
# kept if ANY instance runs that version (or RUNNER_VERSION names it — the
# knob setup.sh honours, so an operator mid-upgrade can protect the new one).
IN_USE_VERSIONS="${RUNNER_VERSION:-}"
for rd in $RUNNER_GLOB; do
  [[ -x "$rd/bin/Runner.Listener" ]] || continue
  v="$("$rd/bin/Runner.Listener" --version 2>/dev/null | tr -d '[:space:]')"
  [[ -n "$v" ]] && IN_USE_VERSIONS="$IN_USE_VERSIONS $v"
done
if [[ -z "${IN_USE_VERSIONS// /}" ]]; then
  echo "[prune] no installed runner version detected — leaving runner tarballs alone"
else
  echo "[prune] runner versions in use: ${IN_USE_VERSIONS# }"
  while IFS= read -r t; do
    tv="$(basename "$t")"; tv="${tv#actions-runner-linux-*-}"; tv="${tv%.tar.gz}"
    case " $IN_USE_VERSIONS " in *" $tv "*) continue ;; esac
    echo "[prune] stale runner tarball: $(basename "$t") ($(human "$(dir_bytes "$t")"))"
    run rm -f "$t"
  done < <(find "$CACHE_ROOT" -maxdepth 1 -name 'actions-runner-linux-*.tar.gz' 2>/dev/null)
fi

# --- report -----------------------------------------------------------------
echo "[prune] Cache root after: $(human "$(dir_bytes "$CACHE_ROOT")")"
echo "[prune] Disk after:  $(df -h / | awk 'NR==2{print $3" used, "$4" free ("$5")"}')"

USED_PCT="$(df / | awk 'NR==2{print $5}' | tr -d '%')"
if (( USED_PCT >= DISK_HIGH_PCT )); then
  echo "::warning::/ is at ${USED_PCT}% (threshold ${DISK_HIGH_PCT}%) even after pruning."
  echo "::warning::The CI caches are bounded; the remaining usage is elsewhere on this host."
  echo "[prune] Largest directories under $HOME:"
  du -sh "$HOME"/* 2>/dev/null | sort -h | tail -8 | sed 's/^/        /'
fi

# Keep the read-only action archive in step with the pins in the workflows
# (the runner never writes to it; see scripts/ci/prime-action-archive.sh).
if [ -x "${CACHE_ROOT}/prime-action-archive.sh" ] && [ -d "${CACHE_ROOT}/gaia.git" ]; then
  tmp_repo="$(mktemp -d)"
  git clone -q --depth 1 "${CACHE_ROOT}/gaia.git" "$tmp_repo" 2>/dev/null \
    && GAIA_REPO="$tmp_repo" bash "${CACHE_ROOT}/prime-action-archive.sh" "${CACHE_ROOT}/actions-archive" \
    || echo "[prune] action archive not primed (mirror clone or gh auth failed)"
  rm -rf "$tmp_repo"
fi
echo "[prune] Done."
