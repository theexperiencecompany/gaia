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
#   pytest xdist: scales linearly to nproc (each worker ~600MB)
#   ruff: scales to nproc (tiny per-file)
#   mypy: dmypy + --jobs nproc gives ~2.5× at 16c vs 2c (still partially serial due to graph)
#   docker buildx: can parallelize layers, but I/O bound

if (( NPROC >= 14 )); then
  NX_PARALLEL=16
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

# Memory guard: pytest workers OOM at ~600MB each → 16 workers needs ~9.6GB
# plus docker layer cache. Cap if MEM_GB is small.
if (( NPROC >= 14 )) && (( MEM_GB < 12 )); then
  NX_PARALLEL=8
  PYTEST_XDIST_N=8
  PYTEST_XDIST="8"
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
