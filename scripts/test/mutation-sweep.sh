#!/usr/bin/env bash
# Full-codebase mutation sweep: run the mutation check on EVERY app module
# (not just PR-changed ones) to find tests that would not notice their code
# being broken. Output: per-module verdict + survivor list.
#
# Usage:  bash scripts/test/mutation-sweep.sh [parallelism] [max-modules]
#   parallelism  - concurrent mutation.sh invocations (default 4)
#   max-modules  - optional cap for a bounded first run
#
# A CPU/memory sampler runs alongside and writes scripts/test/.sweep-stats.log
# (aggregate %CPU and %MEM across the machine every 30s) so the parallelism
# can be tuned from data instead of guesswork.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT/apps/api"

PARALLEL="${1:-4}"
MAX_MODULES="${2:-}"
OUT_DIR="${SWEEP_OUT_DIR:-/tmp/mutation-sweep}"
rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR"

# 1. Every app module except entry points and package markers.
find app -name "*.py" \
  | grep -v __pycache__ \
  | grep -v '/__init__\.py$' \
  | grep -v '^app/main\.py$' \
  | grep -v '^app/worker\.py$' \
  | sort > "$OUT_DIR/modules.txt"
TOTAL="$(wc -l < "$OUT_DIR/modules.txt" | tr -d ' ')"
if [ -n "$MAX_MODULES" ]; then
  head -n "$MAX_MODULES" "$OUT_DIR/modules.txt" > "$OUT_DIR/modules-capped.txt"
  mv "$OUT_DIR/modules-capped.txt" "$OUT_DIR/modules.txt"
  TOTAL="$(wc -l < "$OUT_DIR/modules.txt" | tr -d ' ')"
fi
echo "sweep: $TOTAL modules, $PARALLEL parallel"

# 2. Derive each module's test file with the matrix scanner's logic. Modules
#    with no test anywhere are recorded as a finding (NO_TEST), not a failure.
python3 - "$OUT_DIR/modules.txt" "$OUT_DIR/entries.txt" "$OUT_DIR/no-test.txt" << 'EOF'
import importlib.util
import json
import sys
from pathlib import Path

modules_file, entries_file, no_test_file = sys.argv[1], sys.argv[2], sys.argv[3]
spec = importlib.util.spec_from_file_location(
    "mutation_matrix", Path("../../scripts/ci/mutation-matrix.py")
)
mm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mm)

entries = []
no_test = []
# Parse every test file ONCE (the per-module scan is O(n^2) otherwise:
# 764 modules x ~465 test files each).
tests_dir = Path("tests")
test_files = sorted(tests_dir.rglob("*.py"))
refs_by_test: dict[str, set[str]] = {
    str(p): mm._module_refs(p) for p in test_files if p.name.startswith("test_")
}
module_py_cache: dict[str, str] = {}


def _module_py(rel_py: str) -> str:
    if rel_py not in module_py_cache:
        module_py_cache[rel_py] = f"app.{rel_py.replace('/', '.')}.py"
    return module_py_cache[rel_py]


def _direct_hits(rel_py: str) -> list[str]:
    module = f"app.{rel_py.replace('/', '.')}"
    module_py = _module_py(rel_py)
    hits = []
    for path, refs in refs_by_test.items():
        if mm._matches(module, module_py, refs):
            hits.append(path)
    hits.sort(key=lambda p: (not p.startswith(str(tests_dir / "unit")), p))
    return hits


def _tests_for(rel_py: str, seen: set[str] | None = None) -> list[str]:
    # Mirror mutation-matrix.py's _test_files_for: direct hits, then follow
    # consumers RECURSIVELY (each consumer's own derivation). The one-level
    # version missed modules like app.memory.chroma_store (reachable only
    # through app.memory.engine's own consumer chain).
    hits = _direct_hits(rel_py)
    if hits:
        return hits
    seen = seen or set()
    seen.add(rel_py)
    module = f"app.{rel_py.replace('/', '.')}"
    for consumer in mm._importers_of(module):
        consumer_rel = consumer.removeprefix("app.")
        if consumer_rel in seen:
            continue
        hits = _tests_for(consumer_rel, seen)
        if hits:
            return hits
    return []


for module in Path(modules_file).read_text().splitlines():
    rel = module.removeprefix("apps/api/")
    rel_py = rel.removeprefix("app/").removesuffix(".py")
    # Same selection policy as the CI matrix, from the same function — this
    # used to be a second copy of it, and its mirror check was dead besides
    # (it joined "tests/unit/..." onto tests_dir, giving "tests/tests/unit/...").
    # Run from apps/api, so the repo-relative paths are already correct here.
    testfiles = mm.with_unit_mirror(rel_py, _tests_for(rel_py), Path("."))
    if testfiles:
        entries.append((rel, testfiles))
        continue
    no_test.append(rel)

with open(entries_file, "w") as f:
    for module, testfiles in entries:
        f.write(f"{module} {json.dumps(testfiles, separators=(',', ':'))}\n")
with open(no_test_file, "w") as f:
    for module in no_test:
        f.write(f"{module}\n")
print(f"sweep: {len(entries)} modules with tests, {len(no_test)} without any test file")
EOF

# 3. CPU/memory sampler (30s cadence, machine-wide aggregate).
(
  while true; do
    ps -A -o %cpu= -o %mem= 2>/dev/null | awk '{cpu += $1; mem += $2} END {printf "cpu=%.0f%% mem=%.1f%%\n", cpu, mem}' | sed "s/^/$(date +%H:%M:%S) /" >> "$OUT_DIR/stats.log"
    sleep 30
  done
) &
SAMPLER_PID=$!
trap 'kill "$SAMPLER_PID" 2>/dev/null || true' EXIT

# 4. Run the sweep with bounded parallelism; every verdict lands in its own
#    log so the summary below can classify precisely.
COUNT=0
while read -r module testfiles; do
  COUNT=$((COUNT + 1))
  SLUG="$(echo "$module" | tr '/' '_')"
  bash "$REPO_ROOT/scripts/test/mutation.sh" "$module" "$testfiles" > "$OUT_DIR/$SLUG.log" 2>&1 &
  if [ "$(jobs -r -p | wc -l)" -ge "$PARALLEL" ]; then
    wait -n || true
  fi
  if [ $((COUNT % 25)) -eq 0 ]; then
    echo "sweep: $COUNT/$TOTAL done"
  fi
done < "$OUT_DIR/entries.txt"
wait || true

# 5. Summary: verdicts + survivors (the weak-test findings).
OK=0
SKIP=0
FAIL=0
NO_TEST="$(wc -l < "$OUT_DIR/no-test.txt" | tr -d ' ')"
: > "$OUT_DIR/survivors.txt"
while read -r module testfiles; do
  SLUG="$(echo "$module" | tr '/' '_')"
  LOG="$OUT_DIR/$SLUG.log"
  if grep -q "Mutation: OK" "$LOG"; then
    OK=$((OK + 1))
  elif grep -q "^SKIP:" "$LOG"; then
    SKIP=$((SKIP + 1))
  else
    FAIL=$((FAIL + 1))
    echo "FAIL: $module (see $LOG)" >> "$OUT_DIR/failures.txt"
  fi
  # survivors from FAIL logs too: a module capped mid-run still surfaces
  # real findings in the part that did run
  grep -E "survived" "$LOG" | sed "s|^|$module |" >> "$OUT_DIR/survivors.txt" || true
done < "$OUT_DIR/entries.txt"

echo ""
echo "=== SWEEP SUMMARY ==="
echo "modules with tests : $((OK + SKIP + FAIL))"
echo "  OK (all mutants killed or equivalent) : $OK"
echo "  SKIP (nothing mutatable / tool limits) : $SKIP"
echo "  FAIL (clean-run or infra issue)        : $FAIL"
echo "modules with NO test file at all         : $NO_TEST"
echo "total survivors (weak tests)             : $(grep -c survived "$OUT_DIR/survivors.txt" || true)"
echo ""
echo "=== WEAK TESTS (modules with surviving mutants) ==="
awk '{print $1}' "$OUT_DIR/survivors.txt" | sort | uniq -c | sort -rn | head -40
echo ""
echo "details: $OUT_DIR/"
