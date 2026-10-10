#!/usr/bin/env bash
set -euo pipefail

# Dead Code Detection Script
# Runs vulture (Python) and knip (TypeScript) to find unused code.
# Usage:
#   bash scripts/dead-code-check.sh               # summary only (overview)
#   bash scripts/dead-code-check.sh --verbose     # full details with file names
#   bash scripts/dead-code-check.sh --strict      # exit 1 on findings (CI)

STRICT=false
VERBOSE=false

for arg in "$@"; do
  case "$arg" in
    --strict)
      STRICT=true
      ;;
    --verbose)
      VERBOSE=true
      ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"

# shellcheck source=scripts/ci/lib/log.sh
source "$SCRIPT_DIR/ci/lib/log.sh"

FOUND_ISSUES=false
TOTAL_DEAD_CODE=0

# The findings this run will hand the gate, as `--finding file:line:msg` pairs.
# Collected as the scan reports them rather than re-parsed at the end, so the
# annotation a reader clicks is the line the tool actually named.
VERDICT_ARGS=()
# Past this the annotations bury the summary they are supposed to explain; the
# full list is in the step's own output either way.
MAX_VERDICT_FINDINGS=50

add_finding() {
  ((${#VERDICT_ARGS[@]} / 2 < MAX_VERDICT_FINDINGS)) || return 0
  VERDICT_ARGS+=(--finding "$1:$2:$3")
}

# Colors (disabled if not a terminal)
if [[ -t 1 ]]; then
  BOLD="\033[1m"
  DIM="\033[2m"
  CYAN="\033[36m"
  YELLOW="\033[33m"
  GREEN="\033[32m"
  RED="\033[31m"
  RESET="\033[0m"
else
  BOLD="" DIM="" CYAN="" YELLOW="" GREEN="" RED="" RESET=""
fi

# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

print_header() {
  echo ""
  echo -e "${BOLD}Dead Code Report${RESET}"
  echo "════════════════════════════════════════════════════════"
  echo ""
}

print_section() {
  echo ""
  echo -e "${BOLD}${CYAN}$1${RESET}"
  echo "────────────────────────────────────────────────────────"
  echo ""
}

print_health_bar() {
  local total=$1
  local max_threshold=1000  # Consider 1000+ items as 0% health

  # Calculate health percentage (100% = 0 dead code, 0% = max_threshold+ dead code)
  local health=100
  if [[ $total -gt 0 ]]; then
    health=$(( 100 - (total * 100 / max_threshold) ))
    [[ $health -lt 0 ]] && health=0
  fi

  # Determine color based on health
  local bar_color=$GREEN
  if [[ $health -lt 30 ]]; then
    bar_color=$RED
  elif [[ $health -lt 70 ]]; then
    bar_color=$YELLOW
  fi

  # Build progress bar (50 chars wide)
  local filled=$(( health / 2 ))
  local empty=$(( 50 - filled ))
  local bar=""

  for ((i=0; i<filled; i++)); do
    bar+="█"
  done
  for ((i=0; i<empty; i++)); do
    bar+="░"
  done

  echo ""
  echo -e "  ${BOLD}Codebase Health${RESET}"
  echo ""
  echo -e "  ${bar_color}${bar}${RESET} ${BOLD}${health}%${RESET}"
  echo -e "  ${DIM}($total dead code items found)${RESET}"
  echo ""
}

# ═══════════════════════════════════════════════════════════════
# Python — vulture
# ═══════════════════════════════════════════════════════════════

run_vulture() {
  print_section "Python (vulture)"

  if ! command -v vulture &>/dev/null; then
    echo -e "  ${DIM}vulture not installed, skipping Python dead code check.${RESET}"
    echo -e "  Install: ${CYAN}uv tool install vulture${RESET}"
    echo ""
    return
  fi

  # vulture config lives in [tool.vulture] in the repo-root pyproject.toml, which
  # vulture reads from the CWD — so a bare `vulture` reproduces the CI gate. Tests
  # are excluded there, so a symbol used only by tests is reported as dead.
  #
  # Enforce only functions/methods/classes/properties/unreachable — vulture's
  # high-signal tier. "unused variable"/"unused attribute" are skipped: at conf
  # 60 they're mostly Pydantic fields and external attribute-sets vulture can't
  # see are used, and ruff (F841/F401) already covers unused locals/imports.
  local enforced_re="unused (function|method|class|property)|unreachable code"
  local raw_output
  raw_output=$(vulture 2>&1 | grep -E "$enforced_re" || true)

  if [[ -z "$raw_output" ]]; then
    echo -e "  ${GREEN}No unused code found.${RESET}"
    echo ""
    return
  fi

  FOUND_ISSUES=true

  # vulture already prints file:line:message, so the verdict's findings are a
  # read of its own output — not a second, divergent scan.
  while IFS= read -r line; do
    add_finding "$(echo "$line" | cut -d: -f1)" "$(echo "$line" | cut -d: -f2)" \
      "vulture: $(echo "$line" | cut -d: -f3- | sed 's/^ *//')"
  done <<< "$raw_output"

  if $VERBOSE; then
    # Full detailed output with file names and line numbers
    local current_file="" count=0 file_count=0
    while IFS= read -r line; do
      local file lineno msg
      file=$(echo "$line" | cut -d: -f1)
      lineno=$(echo "$line" | cut -d: -f2)
      msg=$(echo "$line" | cut -d: -f3- | sed 's/^ *//' | sed 's/ ([0-9]*% confidence)//')

      if [[ "$file" != "$current_file" ]]; then
        [[ -n "$current_file" ]] && echo ""
        echo -e "  ${BOLD}$file${RESET}"
        current_file="$file"
        file_count=$((file_count + 1))
      fi
      echo -e "    ${DIM}L${lineno}${RESET}  ${msg}"
      count=$((count + 1))
    done <<< "$raw_output"

    echo ""
    echo ""
    echo -e "  ${YELLOW}Found $count unused items across $file_count files${RESET}"
    TOTAL_DEAD_CODE=$((TOTAL_DEAD_CODE + count))
  else
    # Summary only - just count totals
    local total=0
    local file_count=0
    local current_file=""

    while IFS= read -r line; do
      local file
      file=$(echo "$line" | cut -d: -f1)

      if [[ "$file" != "$current_file" ]]; then
        [[ -n "$current_file" ]] && file_count=$((file_count + 1))
        current_file="$file"
      fi
      total=$((total + 1))
    done <<< "$raw_output"

    # Count last file
    [[ -n "$current_file" ]] && file_count=$((file_count + 1))

    echo -e "  ${YELLOW}Found $total unused items across $file_count files${RESET}"
    echo -e "  ${DIM}Run with --verbose to see details${RESET}"
    TOTAL_DEAD_CODE=$((TOTAL_DEAD_CODE + total))
  fi

  echo ""
}

# ═══════════════════════════════════════════════════════════════
# TypeScript — knip
# ═══════════════════════════════════════════════════════════════

run_knip() {
  print_section "TypeScript (knip)"

  if ! command -v pnpm &>/dev/null; then
    echo -e "  ${DIM}pnpm not found, skipping TypeScript check.${RESET}"
    echo ""
    return
  fi

  # Findings go to stdout; warnings (node's DEP0205, for one) go to stderr.
  # Folding stderr into the findings buffer made a clean run look dirty, so
  # stderr is reported separately and never counted as a finding.
  local raw_output stderr_file knip_status=0
  stderr_file=$(mktemp)
  raw_output=$(pnpm exec knip --config config/knip.config.ts --no-progress --no-config-hints 2>"$stderr_file") \
    || knip_status=$?
  if [[ -s "$stderr_file" ]]; then
    echo -e "  ${DIM}$(cat "$stderr_file")${RESET}"
  fi
  rm -f "$stderr_file"

  # Count total knip findings from its section headers ("Unused files (12)").
  local knip_total=0
  while IFS= read -r line; do
    if [[ "$line" =~ ^[A-Z][a-z]+.*\(([0-9]+)\)$ ]]; then
      local count="${BASH_REMATCH[1]}"
      knip_total=$((knip_total + count))
    fi
  done <<< "$raw_output"

  # Gate on findings and knip's exit status — never on whether it printed
  # anything. Keying off emptiness alone let stderr chatter (today: a Node
  # `module.register()` DeprecationWarning) set FOUND_ISSUES and fail the lane
  # while reporting "0 dead code items found" — a contradiction no edit to the
  # codebase could clear.
  if ((knip_total == 0)); then
    if ((knip_status == 0)); then
      echo -e "  ${GREEN}No unused code found.${RESET}"
      echo ""
      return
    fi
    # Non-zero exit with no findings means knip never scanned (crash, config
    # error, toolchain failure) — an empty report must not read as clean, or the
    # gate goes green exactly when the scan stopped running.
    echo -e "  ${YELLOW}knip exited ${knip_status} with no findings — the scan did not run,${RESET}"
    echo -e "  ${YELLOW}so an empty report cannot mean clean. Failing the gate instead.${RESET}"
    FOUND_ISSUES=true
    return
  fi

  FOUND_ISSUES=true
  TOTAL_DEAD_CODE=$((TOTAL_DEAD_CODE + knip_total))

  # knip's default reporter groups rows under a section header and puts the
  # path (with `:line:col` where it has one) in the row. That is enough to put
  # every finding on the PR's Files tab; a second run with --reporter json
  # would cost the lane a whole extra scan to say the same thing.
  local section=""
  while IFS= read -r line; do
    if [[ "$line" =~ ^[A-Z][a-z]+.*\([0-9]+\)$ ]]; then
      section="${line%% (*}"
    elif [[ "$line" =~ ([^[:space:]]+\.(ts|tsx|js|jsx|mjs|cjs|json|jsonc|css))(:([0-9]+))? ]]; then
      add_finding "${BASH_REMATCH[1]}" "${BASH_REMATCH[4]:-1}" "knip ${section:-finding}: $line"
    fi
  done <<< "$raw_output"

  if $VERBOSE; then
    # Full detailed output
    while IFS= read -r line; do
      # Section headers like "Unused files (12)" or "Unused exports (5)"
      if [[ "$line" =~ ^[A-Z][a-z]+.*\([0-9]+\)$ ]]; then
        echo ""
        echo -e "  ${BOLD}${line}${RESET}"
        echo ""
      elif [[ -n "$line" ]]; then
        echo "    $line"
      fi
    done <<< "$raw_output"
  else
    # Summary only - just show section counts
    while IFS= read -r line; do
      if [[ "$line" =~ ^[A-Z][a-z]+.*\([0-9]+\)$ ]]; then
        echo -e "  ${YELLOW}${line}${RESET}"
      fi
    done <<< "$raw_output"

    echo ""
    echo -e "  ${DIM}Run with --verbose to see details${RESET}"
  fi

  echo ""
}

# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

print_header

run_vulture
run_knip

# Show health score if issues were found
if $FOUND_ISSUES; then
  print_health_bar $TOTAL_DEAD_CODE
fi

# The gate's own wording, once: the paragraph a reader sees below is the same
# sentence the verdict carries to the PR, so the two cannot drift.
DEAD_CODE_FIX="Delete the unused code and every reference to it (imports, re-exports, tests). \
If a symbol is genuinely reached only through dynamic dispatch or a framework entrypoint the \
scanner cannot see, register it — TS: config/knip.config.ts; Python: [tool.vulture] \
ignore_names / ignore_decorators in pyproject.toml, with a comment saying why. \
Never widen the config to silence real dead code."

echo "════════════════════════════════════════════════════════"
if $FOUND_ISSUES && $STRICT; then
  ci_verdict --lane dead-code --status fail \
    --summary "$TOTAL_DEAD_CODE unused item(s) across TypeScript (knip) and Python (vulture)" \
    ${VERDICT_ARGS[@]+"${VERDICT_ARGS[@]}"} \
    --advice "$DEAD_CODE_FIX"
  echo -e "${RED}${BOLD}Dead-code gate FAILED.${RESET}"
  echo ""
  echo -e "${DIM}Why: unused functions, classes, files, and exports rot — they mislead"
  echo -e "readers, break under refactors no one exercises, and hide what is really used.${RESET}"
  echo ""
  echo -e "Fix: for each item listed above. $DEAD_CODE_FIX"
  echo -e "Do not comment it out or keep it \"just in case\"."
  echo ""
  echo -e "Rule: .claude/rules/general.md § \"Dead Code\"."
  exit 1
elif $FOUND_ISSUES; then
  echo -e "${YELLOW}Dead code found (warning only). Use --strict to enforce.${RESET}"
  exit 0
else
  # Only the gated (--strict) run reports: a developer's exploratory run is not
  # a lane, and a verdict it wrote would be uploaded by whatever job lands on
  # this workspace next.
  if $STRICT; then
    ci_verdict --lane dead-code --status pass \
      --summary "no unused TypeScript (knip) or Python (vulture) code"
  fi
  echo -e "${GREEN}No dead code found.${RESET}"
  exit 0
fi
