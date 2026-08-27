#!/usr/bin/env bash
# prune-cache.sh — keep the home runner's persistent CI caches bounded.
#
# Moving the pnpm store, uv cache, Nx cache, Next.js cache and embedding
# models onto local disk is what made the home runner fast (they no longer
# cross the network), but "persistent" means "grows forever" unless something
# bounds it. This is that something.
#
# Bounded by SIZE, not by age. An age-based rule ("delete older than 14d")
# does not bound anything: it is the ingest rate that decides the steady-state
# size, so a busy week silently blows past whatever the disk can hold. Each
# store below gets a byte budget and is trimmed least-recently-used until it
# fits.
#
# What it will delete, and nothing else:
#   * pnpm store (the user's default store, shared with dev tooling) entries
#     nothing references  (pnpm store prune)
#   * uv cache entries for versions no environment uses (uv cache prune)
#   * Nx and Next.js cache entries, LRU, down to their budgets
#   * STOPPED containers named gaia-test-*  (the test services, by exact name)
#   * runner _diag logs beyond the newest DIAG_KEEP
#   * runner tarballs in the cache other than the version in use
#
# What it will NEVER touch, by design:
#   * Docker volumes and images — unrelated to CI caches, and pruning them
#     takes out this host's other services.
#   * The git mirror (it is the seed for every new runner instance).
#   * The embedding models (fixed ~1.4 GB, and re-fetching them costs a
#     multi-minute download).
#
# Usage:
#   bash prune-cache.sh              # dry run: report what WOULD go
#   bash prune-cache.sh --apply      # actually delete
#   CACHE_ROOT=... PNPM_BUDGET_GB=20 bash prune-cache.sh --apply
set -euo pipefail

CACHE_ROOT="${RUNNER_LOCAL_CACHE:-/home/aryan/ci-cache}"
PNPM_BUDGET_GB="${PNPM_BUDGET_GB:-12}"
UV_BUDGET_GB="${UV_BUDGET_GB:-6}"
NX_BUDGET_GB="${NX_BUDGET_GB:-4}"
NEXT_BUDGET_GB="${NEXT_BUDGET_GB:-3}"
DIAG_KEEP="${DIAG_KEEP:-20}"
DISK_HIGH_PCT="${DISK_HIGH_PCT:-85}"
RUNNER_GLOB="${RUNNER_GLOB:-/home/aryan/actions-runner-gaia-home-*}"

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
trim_lru() {
  local dir="$1" budget_gb="$2" label="$3"
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
  done < <(find "$dir" -mindepth 1 -maxdepth 1 -printf '%T@ %p\0' 2>/dev/null \
           | sort -zn | cut -z -d' ' -f2-)
  echo "[prune] $label: reclaimed $(human "$freed")"
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

# --- size-bounded stores ----------------------------------------------------
trim_lru "$(pnpm store path 2>/dev/null || echo "$HOME/.local/share/pnpm/store/v10")" "$PNPM_BUDGET_GB" "pnpm store"
trim_lru "${UV_CACHE_DIR:-$HOME/.cache/uv}" "$UV_BUDGET_GB"   "uv cache"
# The Nx remote cache server evicts LRU itself (NX_CACHE_MAX_BYTES); this is a
# backstop at a slightly larger budget in case the server is down.
trim_lru "${CACHE_ROOT}/nx-remote"  "${NX_REMOTE_BUDGET_GB:-9}" "nx remote cache"
for d in "${CACHE_ROOT}"/*/nx-cache;   do trim_lru "$d" "$NX_BUDGET_GB"   "nx cache ($(basename "$(dirname "$d")"))"; done
for d in "${CACHE_ROOT}"/*/nextjs;     do trim_lru "$d" "$NEXT_BUDGET_GB" "next cache ($(basename "$(dirname "$d")"))"; done
# node_modules trees: keep the newest NM_KEEP lockfile hashes per runner.
NM_KEEP="${NM_KEEP:-2}"
for d in "${CACHE_ROOT}"/*/node_modules-store; do
  [[ -d "$d" ]] || continue
  old="$(find "$d" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' 2>/dev/null | sort -rn | tail -n +$((NM_KEEP + 1)) | cut -d' ' -f2-)"
  if [[ -n "$old" ]]; then
    echo "[prune] $(basename "$(dirname "$d")")/node_modules-store: $(echo "$old" | wc -l) tree(s) beyond newest ${NM_KEEP}"
    # shellcheck disable=SC2086
    run rm -rf $old
  fi
done

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

CURRENT_TARBALL="actions-runner-linux-x64-${RUNNER_VERSION:-2.336.0}.tar.gz"
while IFS= read -r t; do
  [[ "$(basename "$t")" == "$CURRENT_TARBALL" ]] && continue
  echo "[prune] stale runner tarball: $(basename "$t") ($(human "$(dir_bytes "$t")"))"
  run rm -f "$t"
done < <(find "$CACHE_ROOT" -maxdepth 1 -name 'actions-runner-linux-*.tar.gz' 2>/dev/null)

# --- report -----------------------------------------------------------------
echo "[prune] Cache root after: $(human "$(dir_bytes "$CACHE_ROOT")")"
echo "[prune] Disk after:  $(df -h / | awk 'NR==2{print $3" used, "$4" free ("$5")"}')"

USED_PCT="$(df / | awk 'NR==2{print $5}' | tr -d '%')"
if (( USED_PCT >= DISK_HIGH_PCT )); then
  echo "::warning::/ is at ${USED_PCT}% (threshold ${DISK_HIGH_PCT}%) even after pruning."
  echo "::warning::The CI caches are bounded; the remaining usage is elsewhere on this host."
  echo "[prune] Largest directories under /home/aryan:"
  du -sh /home/aryan/* 2>/dev/null | sort -h | tail -8 | sed 's/^/        /'
fi
echo "[prune] Done."
