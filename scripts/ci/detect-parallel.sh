#!/usr/bin/env bash
# detect-parallel.sh — emit optimal parallelism for this runner's CPU count
#
# Insanely great home-server utilization:
#   16 vCPU (8c/16t i7-10700K) should run at full tilt, not at "3".
#   2 vCPU GitHub should stay conservative to avoid OOM/thrashing.
#
# Usage:
#   source scripts/ci/detect-parallel.sh
#   echo $NX_PARALLEL $PYTEST_XDIST $RUFF_JOBS $MYPY_JOBS $DOCKER_JOBS
#
# Or as CLI:  bash scripts/ci/detect-parallel.sh --nx   → 16
#             bash scripts/ci/detect-parallel.sh --pytest → -n 16
#             bash scripts/ci/detect-parallel.sh --env   → export lines for GITHUB_ENV
set -euo pipefail

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
PER_WORKER_GB="${PYTEST_WORKER_GB:-2.5}"
HEADROOM_GB=4   # OS, docker, the runner agent, the coordinating pytest process
MEM_WORKERS="$(awk -v a="$MEM_AVAIL_GB" -v w="$PER_WORKER_GB" -v h="$HEADROOM_GB" 'BEGIN{n=int((a-h)/w); if(n<1)n=1; print n}')"
if (( MEM_WORKERS < PYTEST_XDIST_N )); then
  echo "detect-parallel: memory-capped pytest workers ${PYTEST_XDIST_N} -> ${MEM_WORKERS} (${MEM_AVAIL_GB}G available, ${PER_WORKER_GB}G/worker)" >&2
  PYTEST_XDIST_N="$MEM_WORKERS"
  PYTEST_XDIST="$MEM_WORKERS"
fi
if (( NPROC >= 14 )) && (( MEM_GB < 12 )); then
  NX_PARALLEL=8
fi

emit_env() {
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

case "${1:-}" in
  --nx) echo "$NX_PARALLEL" ;;
  --pytest) echo "$PYTEST_XDIST" ;;
  --pytest-n) echo "$PYTEST_XDIST_N" ;;
  --ruff) echo "$RUFF_JOBS" ;;
  --mypy) echo "$MYPY_JOBS" ;;
  --docker) echo "$DOCKER_JOBS" ;;
  --env) emit_env ;;
  --json) printf '{"nproc":%d,"mem_gb":%d,"nx_parallel":%d,"pytest_xdist":"%s","pytest_xdist_n":%d,"ruff_jobs":%d,"mypy_jobs":%d,"docker_jobs":%d}\n' "$NPROC" "$MEM_GB" "$NX_PARALLEL" "$PYTEST_XDIST" "$PYTEST_XDIST_N" "$RUFF_JOBS" "$MYPY_JOBS" "$DOCKER_JOBS" ;;
  "") emit_env ;;
  *) echo "unknown arg $1" >&2; exit 1 ;;
esac
