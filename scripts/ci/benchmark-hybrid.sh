#!/usr/bin/env bash
# benchmark-hybrid.sh — profile GAIA CI workloads across CPU counts
#
# Compares GitHub 2 vCPU vs home 16c at 2/4/8/16 parallelism so we can quote
# the real speedup, not a guess. Measures wall + sys time via /usr/bin/time.
#
# Usage:
#   bash scripts/ci/benchmark-hybrid.sh [--cpus 2,4,8,16] [--iterations 3] [--workloads ruff,mypy,build,pytest]
#   # On home server via Tailscale:
#   tailscale ssh gaia-home-server "bash ~/gaia/scripts/ci/benchmark-hybrid.sh --iterations 2"
#
# Outputs:
#   scripts/ci/benchmark-results/YYYY-MM-DD_HHMM.csv
#   scripts/ci/benchmark-results/latest.csv  (symlink)
#   stdout: markdown table with median wall time & speedup vs 2c baseline
#
# Each workload is self-contained and cleans up; missing deps are skipped, not failed.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
RESULTS_DIR="$ROOT/scripts/ci/benchmark-results"
mkdir -p "$RESULTS_DIR"

CPUS_LIST="2,4,8,16"
ITERATIONS=1
WORKLOADS="ruff,mypy,build,pytest-hermetic,pytest-live,install"
WARM_CACHE=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --cpus) CPUS_LIST="$2"; shift 2 ;;
    --iterations) ITERATIONS="$2"; shift 2 ;;
    --workloads) WORKLOADS="$2"; shift 2 ;;
    --warm) WARM_CACHE=true; shift ;;
    -h|--help)
      echo "Usage: $0 [--cpus 2,4,8,16] [--iterations N] [--workloads LIST] [--warm]"
      exit 0 ;;
    *) echo "::error::Unknown arg $1"; exit 1 ;;
  esac
done

IFS=',' read -ra CPUS_ARR <<< "$CPUS_LIST"
IFS=',' read -ra WL_ARR <<< "$WORKLOADS"

TIMESTAMP="$(date +%Y-%m-%d_%H%M)"
CSV="$RESULTS_DIR/${TIMESTAMP}.csv"
echo "workload,cpus,iteration,wall_s,cpu_s,max_rss_kb,exit_code,hostname,nproc,runner_label,notes" > "$CSV"

HOST="$(hostname)"
NPROC="$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 2)"
RUNNER_LABEL="${RUNNER_LABEL:-$HOST}"

have() { command -v "$1" >/dev/null 2>&1; }

# Detect /usr/bin/time flavour (GNU vs BSD). Prefer GNU for -v.
TIME_BIN="/usr/bin/time"
if ! "$TIME_BIN" --version 2>&1 | grep -q "GNU"; then
  # macOS: try gtime (coreutils shim at /opt/homebrew/bin/timeout)
  if have gtime; then TIME_BIN="gtime"
  elif have /opt/homebrew/bin/gtime; then TIME_BIN="/opt/homebrew/bin/gtime"
  else TIME_BIN="/usr/bin/time" # will use BSD -l
  fi
fi
TIME_IS_GNU=false
if "$TIME_BIN" --version 2>&1 | grep -q "GNU"; then TIME_IS_GNU=true; fi

run_timed() {
  local workload="$1" cpus="$2" iter="$3"
  local wall_s="NA" cpu_s="NA" rss="NA" exit_code=0 notes=""
  local log="/tmp/bench-${workload}-${cpus}c-${iter}.log"
  local time_log="/tmp/bench-${workload}-${cpus}c-${iter}.time"

  # Workload command is set by caller via $CMD
  set +e
  if $TIME_IS_GNU; then
    # GNU: --output + --format
    $TIME_BIN -v --output="$time_log" bash -c "$CMD" >"$log" 2>&1
    exit_code=$?
    wall_s=$(awk '/Elapsed.*wall clock/{print $8}' "$time_log" 2>/dev/null | awk -F: '{if(NF==3) print $1*3600+$2*60+$3; else if(NF==2) print $1*60+$2; else print $1}' 2>/dev/null || echo NA)
    cpu_s=$(awk '/User time/{print $4}' "$time_log" 2>/dev/null || echo NA)
    rss=$(awk '/Maximum resident/{print $6}' "$time_log" 2>/dev/null || echo NA)
    if [[ "$wall_s" == "NA" ]]; then
      wall_s=$(awk '/Elapsed/{print $NF}' "$time_log" 2>/dev/null | tr -d '()' || echo NA)
    fi
  else
    # BSD: -l -o ; wall is "real"
    START=$(python3 -c "import time; print(time.time())" 2>/dev/null || date +%s)
    $TIME_BIN -l -o "$time_log" bash -c "$CMD" >"$log" 2>&1
    exit_code=$?
    END=$(python3 -c "import time; print(time.time())" 2>/dev/null || date +%s)
    wall_s=$(python3 -c "print(round(float('$END')-float('$START'),2))" 2>/dev/null || echo NA)
    rss=$(awk '/maximum resident set size/{print $1}' "$time_log" 2>/dev/null || echo NA)
    cpu_s="NA"
  fi
  set -e

  # Fallback wall: parse with python if still NA
  if [[ "$wall_s" == "NA" || -z "$wall_s" ]]; then
    wall_s=$(python3 -c "
import pathlib, re
t=pathlib.Path('$time_log').read_text(errors='ignore')
for pat in [r'Elapsed.*\(([^)]+)\)', r'real\s+([0-9:.]+)', r'Elapsed.*?([0-9:.]+)']:
    m=re.search(pat, t)
    if m:
        s=m.group(1)
        parts=list(map(float, s.split(':')))
        if len(parts)==3: print(parts[0]*3600+parts[1]*60+parts[2]); break
        if len(parts)==2: print(parts[0]*60+parts[1]); break
        print(parts[0]); break
else: print('NA')
" 2>/dev/null || echo NA)
  fi

  echo "$workload,$cpus,$iter,$wall_s,$cpu_s,$rss,$exit_code,$HOST,$NPROC,$RUNNER_LABEL,\"$notes\"" >> "$CSV"
  printf "  %-18s %2sc  iter %d/%d  wall=%-8s  cpu=%-8s  exit=%d  %s\n" "$workload" "$cpus" "$iter" "$ITERATIONS" "${wall_s}s" "${cpu_s}s" "$exit_code" "$(head -n1 "$log" 2>/dev/null | cut -c1-80)"
  if (( exit_code != 0 )); then
    echo "    last 20 lines of $log:" >&2
    tail -n 20 "$log" >&2 | sed 's/^/    | /' || true
  fi
}

echo "[bench] Host: $HOST  nproc=$NPROC  time=$TIME_BIN (gnu=$TIME_IS_GNU)"
echo "[bench] CPUS: ${CPUS_ARR[*]}  iterations: $ITERATIONS  workloads: ${WL_ARR[*]}"
echo "[bench] Results: $CSV"
echo ""

for workload in "${WL_ARR[@]}"; do
  case "$workload" in
    install)
      CMD="pnpm install --frozen-lockfile --prefer-offline 2>&1 | tail -n 5"
      if ! have pnpm; then echo "[bench] skip install — pnpm not found"; continue; fi
      ;;
    build)
      CMD="pnpm exec nx run-many -t build --parallel=CPUS_PLACEHOLDER 2>&1 | tail -n 30"
      if ! have pnpm; then echo "[bench] skip build — pnpm not found"; continue; fi
      ;;
    ruff)
      CMD="uvx --no-build ruff@0.14.13 check . 2>&1 | tail -n 20"
      ;;
    mypy)
      CMD="uv run --project apps/api --frozen --group backend --group dev mypy apps/api/app apps/voice-agent/src libs/shared/py --ignore-missing-imports 2>&1 | tail -n 30"
      ;;
    pytest-hermetic)
      CMD="uv run --frozen pytest -n CPUS_PLACEHOLDER -m 'not composio and not model_onboarding and not schemathesis' --tb=line -q --override-ini=addopts=--strict-markers --timeout=300 2>&1 | tail -n 30"
      ;;
    pytest-live)
      CMD="bash scripts/ci/start-test-services.sh >/tmp/bench-services.log 2>&1 && uv run --frozen pytest -n CPUS_PLACEHOLDER -m 'not composio and not model_onboarding and not schemathesis' --tb=line -q --override-ini=addopts=--strict-markers --timeout=300 --durations=10 2>&1 | tail -n 30; docker rm -f gaia-test-postgres gaia-test-redis gaia-test-mongo gaia-test-chroma gaia-test-rabbitmq 2>/dev/null | true"
      if ! have docker; then echo "[bench] skip pytest-live — docker not found"; continue; fi
      ;;
    xenon|interrogate|biome)
      CMD="echo 'workload $workload not yet mapped' && false"
      ;;
    *) echo "[bench] unknown workload $workload — skipping"; continue ;;
  esac

  for cpus in "${CPUS_ARR[@]}"; do
    # Substitute placeholder
    CMD_EXPANDED="${CMD//CPUS_PLACEHOLDER/$cpus}"
    # For pytest, also constrain via taskset when cpus < nproc for fair comparison
    if [[ "$workload" == ruff* ]] && (( cpus < NPROC )) && have taskset; then
      CMD_EXPANDED="taskset -c 0-$((cpus-1)) bash -c '$CMD_EXPANDED'"
    fi
    export CMD="$CMD_EXPANDED"
    echo "[bench] === $workload @ ${cpus}c ==="
    for iter in $(seq 1 "$ITERATIONS"); do
      run_timed "$workload" "$cpus" "$iter"
    done
    # restore template for next cpu
    case "$workload" in
      install) CMD="pnpm install --frozen-lockfile --prefer-offline 2>&1 | tail -n 5" ;;
      build) CMD="pnpm exec nx run-many -t build --parallel=CPUS_PLACEHOLDER 2>&1 | tail -n 30" ;;
      ruff) CMD="uvx --no-build ruff@0.14.13 check . 2>&1 | tail -n 20" ;;
      mypy) CMD="uv run --project apps/api --frozen --group backend --group dev mypy apps/api/app apps/voice-agent/src libs/shared/py --ignore-missing-imports 2>&1 | tail -n 30" ;;
      pytest-hermetic) CMD="uv run --frozen pytest -n CPUS_PLACEHOLDER -m 'not composio and not model_onboarding and not schemathesis' --tb=line -q --override-ini=addopts=--strict-markers --timeout=300 2>&1 | tail -n 30" ;;
      pytest-live) CMD="bash scripts/ci/start-test-services.sh >/tmp/bench-services.log 2>&1 && uv run --frozen pytest -n CPUS_PLACEHOLDER -m 'not composio and not model_onboarding and not schemathesis' --tb=line -q --override-ini=addopts=--strict-markers --timeout=300 --durations=10 2>&1 | tail -n 30; docker rm -f gaia-test-postgres gaia-test-redis gaia-test-mongo gaia-test-chroma gaia-test-rabbitmq 2>/dev/null | true" ;;
    esac
  done
  echo ""
done

ln -sf "$(basename "$CSV")" "$RESULTS_DIR/latest.csv"
echo "[bench] CSV written: $CSV"
echo "[bench] Symlink: $RESULTS_DIR/latest.csv -> $(basename "$CSV")"

# --- markdown summary (median wall time + speedup vs 2c) ---
echo ""
echo "[bench] Generating markdown summary..."
python3 <<PY
import csv, pathlib, statistics
csv_path = pathlib.Path("$CSV")
rows = list(csv.DictReader(csv_path.read_text().splitlines()))
if not rows:
    print("No rows")
    exit(0)
# Group by workload,cpus -> list of wall_s
from collections import defaultdict
grouped = defaultdict(list)
for r in rows:
    try:
        w = float(r["wall_s"])
        if w>0:
            grouped[(r["workload"], int(r["cpus"]))].append(w)
    except: pass

workloads = sorted({k[0] for k in grouped})
cpus_sorted = sorted({k[1] for k in grouped})

# median per cell
medians = {}
for (wl, c), vals in grouped.items():
    medians[(wl,c)] = statistics.median(vals)

print("\n### Benchmark medians (wall seconds, {} iteration(s) each)".format("$ITERATIONS"))
print(f"Host: $HOST — {__import__('os').cpu_count()} logical? nproc=$NPROC")
print("")
header = "| Workload | " + " | ".join(f"{c}c" for c in cpus_sorted) + " | Speedup 16c vs 2c |"
print(header)
print("|" + "---|"* (len(cpus_sorted)+2))
for wl in workloads:
    vals = [medians.get((wl,c), None) for c in cpus_sorted]
    baseline = medians.get((wl, min(cpus_sorted)), None)
    # Pretty row
    cells = []
    for v in vals:
        cells.append(f"{v:.1f}s" if v is not None else "—")
    if baseline and medians.get((wl, max(cpus_sorted))):
        speedup = baseline / medians[(wl, max(cpus_sorted))]
        sp = f"{speedup:.1f}×"
    else:
        sp = "—"
    print(f"| {wl} | " + " | ".join(cells) + f" | {sp} |")

print("")
print("Raw CSV: `scripts/ci/benchmark-results/{}`".format(csv_path.name))
# Also write docs/ci/HYBRID_BENCHMARK.md fragment
out = pathlib.Path("$ROOT/docs/ci/HYBRID_BENCHMARK.md")
out.parent.mkdir(parents=True, exist_ok=True)
import datetime
front = f"""# Hybrid CI Benchmark — {datetime.date.today().isoformat()}

Home: `{HOST}` — {__import__('platform').processor() or 'x86_64'} — `$NPROC` threads — 46 GiB

Median wall time, {ITERATIONS} iteration(s) per cell (taskset-pinned when cpus < nproc).

"""
front += header + "\n" + "|" + "---|"* (len(cpus_sorted)+2) + "\n"
for wl in workloads:
    vals = [medians.get((wl,c), None) for c in cpus_sorted]
    baseline = medians.get((wl, min(cpus_sorted)), None)
    cells = [f"{v:.1f}s" if v is not None else "—" for v in vals]
    if baseline and medians.get((wl, max(cpus_sorted))):
        sp = f"{baseline/medians[(wl, max(cpus_sorted))]:.1f}×"
    else: sp="—"
    front += f"| {wl} | " + " | ".join(cells) + f" | {sp} |\n"
front += f"\nRaw: `scripts/ci/benchmark-results/{csv_path.name}` — baseline 2c is GitHub 2 vCPU proxy (taskset) or home 2c.\n"
front += """
Notes:
- `install` is pnpm cold (rm -rf node_modules) vs warm (--prefer-offline) — first is network-bound.
- `mypy` is largely single-threaded; gains are from parallel workers where supported.
- `pytest-hermetic` benefits most (xdist -n auto ≈ nproc).
- Dockerized live-services adds container start (~15s) — home NVMe helps on pulls.
"""
out.write_text(front)
print(f"[bench] Markdown → {out}")
PY
