#!/usr/bin/env bash
# cpu-slots.sh — a WEIGHTED, FAIL-OPEN host CPU semaphore, sourced like log.sh.
#
# Why this exists: the home CI box is 8 physical cores / 16 threads, but the
# heavy lanes size their own parallelism independently and land together. The
# four test-python slices alone budget ~16 threads; on the SAME cores at the
# same time run main.yml's `build` (nx --parallel 6), `test-typescript`,
# `docker-image`, and the whole of code-quality.yml (mypy, semgrep, and the
# sharded `mutation.sh shard`, four at a time each wanting nproc-2). Two
# overlapping pushes double it. The 15-min load average has been measured at
# ~18.5 (2.3x oversubscription); the SAME PR ran 3.6 min idle vs 11.3 min
# loaded. This governor caps the concurrent heavy work at the physical-core
# budget so lanes QUEUE instead of thrash.
#
# It is a counting semaphore over a token pool held in a HOST-SHARED directory
# (every runner instance on the box shares it — that is the whole point). A
# lane acquires tokens equal to its real thread appetite, runs, releases.
#
# Contract (the only two functions callers use):
#   cpu_slots_acquire N   Block until N tokens are free (or the pool is smaller
#                         than N and fully free), then take them. Installs an
#                         EXIT trap so they are always released.
#   cpu_slots_release N   Give N tokens back.
#
# It NEVER hangs or fails a gate. It is a no-op (returns success, takes nothing)
# when:
#   * RUNNER_ENVIRONMENT != self-hosted  — GitHub-hosted VMs are isolated, one
#     job per VM; there is nothing to govern and no shared box.
#   * the pool directory cannot be created.
#   * N is not a positive integer (a serial slice passes XDIST_N=0).
#   * the acquire waits past GAIA_CPU_SLOTS_TIMEOUT (default 600s) — it logs a
#     ::warning:: and PROCEEDS WITHOUT the tokens (fail-open: oversubscribe
#     rather than block a gate on the governor).
#
# State model — the holders directory IS the counter, so it cannot drift.
# Available tokens are computed every time under the lock as
#   TOTAL - sum(tokens of live holder files)
# rather than kept in a mutable counter that a crashed job could leave wrong.
# Each held grant is one file `holders/<pid>.<nonce>` whose contents are the
# token count. A grant is reclaimed (the file removed) the moment its holder
# pid is dead — this is the SIGKILL leak fix: a cancelled job killed with
# SIGKILL never runs its EXIT trap, but the next acquirer sees its pid is gone
# and reclaims the tokens. A grant older than GAIA_CPU_SLOTS_TTL (default
# 3600s, longer than any lane) is reclaimed too, in case a dead pid was recycled
# onto an unrelated process. All reads and the take are inside one `flock`, so
# there is no TOCTOU.
#
# Env:
#   GAIA_CPU_TOKENS         Pool size (TOTAL). Default: the thread count (nproc,
#                           16 on the box). At nproc a single run's own xdist
#                           workers fit exactly, so a lone run never blocks
#                           (neutral) while two overlapping runs are held to the
#                           thread count instead of thrashing to ~4x.
#   GAIA_CPU_SLOTS_DIR      Override the pool directory (tests point this at a
#                           throwaway path).
#   GAIA_CPU_SLOTS_TIMEOUT  Max seconds to wait before failing open (600).
#   GAIA_CPU_SLOTS_TTL      Seconds after which a grant is presumed leaked (3600).
#   RUNNER_ENVIRONMENT      "self-hosted" enables the governor; anything else is
#                           a no-op.
#
# Sourced, never executed: it defines functions and touches nothing at source
# time (log.sh must already be sourced — it provides ci_warn).

# Parallel stacks of grants this shell currently holds (bash 3.2 has no
# associative arrays, and these scripts reach a mac). Index i pairs a holder
# file with the token count it represents.
_CPU_SLOTS_HELD_FILES=()
_CPU_SLOTS_HELD_N=()

_cpu_slots_enabled() { [ "${RUNNER_ENVIRONMENT:-}" = "self-hosted" ]; }

# flock is the atomicity primitive; without it there is no safe critical section,
# so the governor fails open rather than race. It is coreutils/util-linux and is
# always present on the Linux box (the only place RUNNER_ENVIRONMENT is
# self-hosted); this guard matters for a dev machine that force-enables the
# governor without it (e.g. a stock macOS running the tests).
_cpu_slots_have_flock() { command -v flock >/dev/null 2>&1; }

_cpu_slots_is_uint() { case "$1" in ''|*[!0-9]*) return 1 ;; *) return 0 ;; esac }

# Echo the resolved, existing pool directory; return non-zero if none is
# writable (caller then fails open). Preference: an explicit override, then the
# host-global /run tmpfs, then $HOME/ci-cache — the latter is shared across every
# runner instance because they share $HOME (runner.sh's action-archive cache
# lives there for the same reason). RUNNER_LOCAL_CACHE is deliberately NOT used:
# it is namespaced PER runner instance, so a pool under it would give each of the
# box's runners its own private budget and defeat the host-wide cap entirely.
_cpu_slots_dir() {
  local dir
  if [ -n "${GAIA_CPU_SLOTS_DIR:-}" ]; then
    dir="$GAIA_CPU_SLOTS_DIR"
  elif mkdir -p /run/gaia-ci 2>/dev/null && [ -w /run/gaia-ci ]; then
    dir="/run/gaia-ci/cpu-slots"
  else
    dir="${HOME:-/tmp}/ci-cache/cpu-slots"
  fi
  mkdir -p "$dir/holders" 2>/dev/null || return 1
  printf '%s' "$dir"
}

# The pool size. A configured value wins; otherwise the THREAD count (nproc).
# This was tuned by measurement, not assumed: the four test-python slices' static
# worker shares (5+7+4) are deliberately sized to sum to the box's 16 threads for
# a SINGLE run, so a pool below that (e.g. physical cores = 8) would serialise a
# lone run's own slices and regress the single-push case. At nproc the pool is a
# no-op for a single run (its 16 workers exactly fit) yet still halves the
# oversubscription when TWO runs overlap — measured on two concurrent main.yml
# dispatches: the 1-min loadavg peak dropped from 59 (governor off) to 32 (pool
# = 16) on the 16-thread box, with per-run wall going 6.4/6.1 min -> 5.5/4.8 min.
_cpu_slots_total() {
  if _cpu_slots_is_uint "${GAIA_CPU_TOKENS:-}" && [ "${GAIA_CPU_TOKENS}" -ge 1 ]; then
    printf '%s' "$GAIA_CPU_TOKENS"
    return
  fi
  printf '%s' "$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 2)"
}

_cpu_slots_jitter() { awk -v r="$RANDOM" 'BEGIN { srand(r); printf "%.2f", 1 + rand()*2 }'; }

# Chain onto any existing EXIT trap instead of clobbering it — cmd_shard and
# others already own EXIT for their own cleanup. Idempotent: only the first
# acquire in a shell installs the chain; later grants ride the same trap and are
# freed by _cpu_slots_release_all, which drains whatever is still held.
_cpu_slots_add_exit_trap() {
  [ "${_CPU_SLOTS_TRAP_SET:-}" = "1" ] && return
  local prev
  prev="$(trap -p EXIT | sed "s/^trap -- '//; s/' EXIT\$//")"
  if [ -n "$prev" ]; then
    # shellcheck disable=SC2064 # deliberate: bake the previous trap body in now so we chain onto it instead of clobbering it
    trap "_cpu_slots_release_all; ${prev}" EXIT
  else
    trap '_cpu_slots_release_all' EXIT
  fi
  _CPU_SLOTS_TRAP_SET=1
}

# Under the lock: sum live grants, reclaiming dead or stale ones as we go, and
# print the result. A grant is live iff its pid is still running AND it is
# younger than the TTL. This is the reaper AND the counter in one pass.
_cpu_slots_live_locked() {
  local holders="$1" ttl="$2" live=0 f base pid n
  for f in "$holders"/*; do
    [ -e "$f" ] || continue
    base="${f##*/}"; pid="${base%%.*}"
    if ! _cpu_slots_is_uint "$pid" || ! kill -0 "$pid" 2>/dev/null; then
      rm -f "$f"; continue
    fi
    if [ -n "$ttl" ] && [ -n "$(find "$f" -mmin +"$(( ttl / 60 ))" -print 2>/dev/null)" ]; then
      rm -f "$f"; continue
    fi
    n="$(cat "$f" 2>/dev/null)"
    _cpu_slots_is_uint "$n" && live=$(( live + n ))
  done
  printf '%s' "$live"
}

cpu_slots_acquire() {
  local want="${1:-}"
  _cpu_slots_enabled || return 0
  if ! _cpu_slots_is_uint "$want" || [ "$want" -lt 1 ]; then return 0; fi
  if ! _cpu_slots_have_flock; then
    ci_warn "cpu-slots: flock not found — proceeding without the governor (fail-open)"
    return 0
  fi

  local dir total
  if ! dir="$(_cpu_slots_dir)"; then
    ci_warn "cpu-slots: no writable pool dir — proceeding without the governor (fail-open)"
    return 0
  fi
  total="$(_cpu_slots_total)"
  # Never wait for more than exists: a lane whose appetite exceeds the whole
  # pool (mutation wants nproc-2 on an 8-token pool) takes the pool and blocks
  # the rest, which is exactly the intended serialization.
  [ "$want" -gt "$total" ] && want="$total"

  local lock="$dir/lock" holders="$dir/holders"
  local ttl="${GAIA_CPU_SLOTS_TTL:-3600}"
  local timeout="${GAIA_CPU_SLOTS_TIMEOUT:-600}"
  # +1 because `date +%s` truncates to whole seconds: a start at X.9 reads X, so a
  # bare `X + timeout` deadline is crossed after only `timeout - 0.9`s of real
  # time and fails open BEFORE the timeout it promised. The extra second absorbs
  # that sub-second truncation so the wait always covers at least `timeout`.
  local deadline=$(( $(date +%s) + timeout + 1 ))
  local nonce="${RANDOM}${RANDOM}"
  local holderfile="$holders/$$.$nonce"

  while :; do
    local rc=0
    (
      flock 9 || exit 3
      local live avail
      live="$(_cpu_slots_live_locked "$holders" "$ttl")"
      avail=$(( total - live )); [ "$avail" -lt 0 ] && avail=0
      if [ "$avail" -ge "$want" ]; then
        printf '%s' "$want" > "$holderfile"
        exit 0
      fi
      exit 1
    ) 9>"$lock" || rc=$?

    if [ "$rc" -eq 0 ]; then
      _CPU_SLOTS_HELD_FILES+=("$holderfile")
      _CPU_SLOTS_HELD_N+=("$want")
      _cpu_slots_add_exit_trap
      return 0
    fi
    if [ "$(date +%s)" -ge "$deadline" ]; then
      ci_warn "cpu-slots: waited ${timeout}s for ${want} token(s) and never got them — proceeding WITHOUT them (fail-open, box may be oversubscribed)"
      return 0
    fi
    sleep "$(_cpu_slots_jitter)"
  done
}

# Return one grant of exactly N tokens (the matching acquire). Removes its holder
# file under the lock; available is recomputed from holders, so there is nothing
# else to update. Unknown/no-op grants (governor disabled, N<=0, or a fail-open
# acquire that took nothing) simply have no holder file and this is a no-op.
cpu_slots_release() {
  local give="${1:-}"
  _cpu_slots_enabled || return 0
  if ! _cpu_slots_is_uint "$give" || [ "$give" -lt 1 ]; then return 0; fi

  local dir
  dir="$(_cpu_slots_dir)" || return 0
  local total
  total="$(_cpu_slots_total)"
  [ "$give" -gt "$total" ] && give="$total"

  # Find the most recent grant matching this token count and drop it.
  local i idx=-1
  for (( i=${#_CPU_SLOTS_HELD_N[@]}-1; i>=0; i-- )); do
    if [ "${_CPU_SLOTS_HELD_N[$i]}" = "$give" ]; then idx=$i; break; fi
  done
  [ "$idx" -lt 0 ] && return 0

  local hf="${_CPU_SLOTS_HELD_FILES[$idx]}"
  (
    flock 9 || exit 0
    rm -f "$hf"
  ) 9>"$dir/lock"
  _cpu_slots_forget "$idx"
}

# Rebuild the held-grant stacks without index $1 (bash 3.2 has no element unset
# that renumbers, so rebuild explicitly).
_cpu_slots_forget() {
  local drop="$1" i
  local nf=() nn=()
  for (( i=0; i<${#_CPU_SLOTS_HELD_FILES[@]}; i++ )); do
    [ "$i" -eq "$drop" ] && continue
    nf+=("${_CPU_SLOTS_HELD_FILES[$i]}")
    nn+=("${_CPU_SLOTS_HELD_N[$i]}")
  done
  _CPU_SLOTS_HELD_FILES=(${nf[@]+"${nf[@]}"})
  _CPU_SLOTS_HELD_N=(${nn[@]+"${nn[@]}"})
}

# EXIT-trap safety net: free every grant this shell still holds. Runs on normal
# exit, failure, and SIGTERM (the trap is on EXIT, which fires for those); a
# SIGKILL cannot run it, which is what the dead-pid reaper covers instead.
_cpu_slots_release_all() {
  if ! _cpu_slots_have_flock; then _CPU_SLOTS_HELD_FILES=(); _CPU_SLOTS_HELD_N=(); return 0; fi
  local dir
  dir="$(_cpu_slots_dir 2>/dev/null)" || return 0
  local i
  (
    flock 9 || exit 0
    for (( i=0; i<${#_CPU_SLOTS_HELD_FILES[@]}; i++ )); do
      rm -f "${_CPU_SLOTS_HELD_FILES[$i]}"
    done
  ) 9>"$dir/lock"
  _CPU_SLOTS_HELD_FILES=()
  _CPU_SLOTS_HELD_N=()
}
