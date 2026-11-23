#!/usr/bin/env bash
# audit.sh — the standing checks on what we depend on and what we emit.
#
# Subcommands:
#   pnpm               Fail-loud `pnpm audit` gate for the JS workspace, with
#                      an allowlist that requires an owner, a reason and an
#                      expiry (an expired entry fails).
#   pip                Fail-loud `pip-audit` gate over the uv.lock export.
#   playwright-pin     apps/api/Dockerfile's PLAYWRIGHT_VERSION must equal the
#                      playwright version in uv.lock.
#   model-pin          apps/api/Dockerfile's baked EMBEDDING_MODEL/RERANKER_MODEL
#                      must equal the model names in app/constants/memory.py.
#   alert-rule-tools   Install pinned pint + promtool for the alert-rules lane
#                      into $RUNNER_TEMP/bin and prepend it to $GITHUB_PATH.
#   evlog              Per-file observability ratchet over the changed Python
#                      files: a file whose score dropped fails the lane.
#   uv-lock            Every tracked uv.lock must still resolve from its
#                      pyproject.toml (`uv lock --check`), standalone projects
#                      outside the root workspace included.
#   secrets --lane L   Pinned gitleaks over every commit this change adds,
#                      merged-in branches included: base-rev..HEAD on a PR and
#                      a merge group, the pushed range on a push.
#
# Both audits fail on every advisory at or above their level, on a PR as on
# master, as trivy does: a CVE in what master already ships blocks the next
# change until the package is bumped or the advisory is allowlisted with a
# reason. Dependabot security updates open the bump.
#
# Env contract:
#   pnpm              PNPM_AUDIT_LEVEL (high),
#                     PNPM_AUDIT_ALLOWLIST (config/pnpm-audit-allowlist.json),
#                     PNPM_AUDIT_TODAY (tests), PNPM_AUDIT_ROOT (tests).
#                     Exit: 0 clean / all allowlisted; 1 findings or expired
#                     entries; 2 the audit itself could not run.
#   pip               PIP_AUDIT_ROOT (tests), RUNNER_TEMP. Exit codes as pnpm's.
#   playwright-pin    none.
#   model-pin         none.
#   alert-rule-tools  RUNNER_TEMP (required), GITHUB_PATH.
#   evlog             GAIA_PR_BASE or GITHUB_BASE_REF (optional; falls back to
#                     NX_BASE/master locally), RUNNER_TEMP; needs a fetch-depth: 0
#                     checkout.
#   uv-lock           UV_LOCK_ROOT (tests; defaults to the repo root). Needs uv
#                     and index access. Exit: 0 all current; 1 any stale lock.
#   secrets           GAIA_PR_BASE (PR, merge group) or PUSH_BEFORE_SHA (push),
#                     GITLEAKS_CACHE (the release tarball's cache dir), RUNNER_TEMP;
#                     GITLEAKS_RELEASE_URL / GITLEAKS_SHA256 replace the pin
#                     only for the script's own tests;
#                     SECRETS_ROOT (tests; defaults to the repo root);
#                     needs a fetch-depth: 0 checkout. Exit: 0 clean; 1 a
#                     finding (its verdict written from the SARIF) or a failed scan.
set -euo pipefail

# shellcheck source=scripts/ci/lib/log.sh
source "$(dirname "$0")/lib/log.sh"
# shellcheck source=scripts/ci/lib/pinned-release.sh
source "$(dirname "$0")/lib/pinned-release.sh"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

cmd_pnpm() {

  ROOT="${PNPM_AUDIT_ROOT:-$REPO_ROOT}"
  ALLOWLIST="${PNPM_AUDIT_ALLOWLIST:-$ROOT/config/pnpm-audit-allowlist.json}"
  LEVEL="${PNPM_AUDIT_LEVEL:-high}"
  TODAY="${PNPM_AUDIT_TODAY:-$(date -u +%Y-%m-%d)}"

  if [ ! -f "$ALLOWLIST" ]; then
    echo "::error::audit pnpm: allowlist not found at $ALLOWLIST" >&2
    exit 2
  fi

  tmp=$(mktemp -d)
  trap 'rm -rf "$tmp"' EXIT

  # --prod: only dependencies/optionalDependencies reach a build or a runtime,
  # devDependencies are gated separately by Dependabot. pnpm exits non-zero
  # whenever it found anything, so do not let that abort the script here.
  set +e
  pnpm --dir "$ROOT" audit --prod --json >"$tmp/audit.json" 2>"$tmp/audit.err"
  pnpm_exit=$?
  set -e

  AUDIT_JSON="$tmp/audit.json" AUDIT_ERR="$tmp/audit.err" PNPM_EXIT="$pnpm_exit" \
  ALLOWLIST="$ALLOWLIST" LEVEL="$LEVEL" TODAY="$TODAY" node - <<'NODE'
const fs = require("node:fs");
const { AUDIT_JSON, AUDIT_ERR, PNPM_EXIT, ALLOWLIST, LEVEL, TODAY } = process.env;
const RANK = { low: 0, moderate: 1, high: 2, critical: 3 };
const fail = (msg, code) => { console.error(`::error::pnpm-audit: ${msg}`); process.exit(code); };

if (!(LEVEL in RANK)) fail(`PNPM_AUDIT_LEVEL must be one of ${Object.keys(RANK).join("|")}, got "${LEVEL}"`, 2);
if (!/^\d{4}-\d{2}-\d{2}$/.test(TODAY)) fail(`bad date "${TODAY}"`, 2);

let report;
try {
  report = JSON.parse(fs.readFileSync(AUDIT_JSON, "utf8"));
  if (!report || typeof report.advisories !== "object") throw new Error("no advisories field");
} catch (e) {
  const err = fs.readFileSync(AUDIT_ERR, "utf8").trim();
  fail(`pnpm audit produced no usable report (exit ${PNPM_EXIT}): ${e.message}\n${err}`, 2);
}

let allow;
try {
  allow = JSON.parse(fs.readFileSync(ALLOWLIST, "utf8")).allow;
  if (!Array.isArray(allow)) throw new Error('"allow" must be an array');
  for (const e of allow) {
    if (!/^(CVE-\d{4}-\d{4,}|GHSA-[0-9a-z]{4}-[0-9a-z]{4}-[0-9a-z]{4})$/.test(e.id || "")) throw new Error(`bad id ${JSON.stringify(e.id)}`);
    if (!e.reason || typeof e.reason !== "string") throw new Error(`${e.id}: reason is required`);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(e.expires || "")) throw new Error(`${e.id}: expires must be YYYY-MM-DD`);
  }
} catch (e) {
  fail(`malformed allowlist ${ALLOWLIST}: ${e.message}`, 2);
}

const expired = allow.filter((e) => e.expires < TODAY);
const active = new Map(allow.filter((e) => e.expires >= TODAY).map((e) => [e.id, e]));
const used = new Set();

const bySeverity = { low: 0, moderate: 0, high: 0, critical: 0 };
const failing = [];
const suppressed = [];
for (const a of Object.values(report.advisories)) {
  bySeverity[a.severity] = (bySeverity[a.severity] || 0) + 1;
  if ((RANK[a.severity] ?? -1) < RANK[LEVEL]) continue;
  const ids = [a.github_advisory_id, ...(a.cves || [])].filter(Boolean);
  const hit = ids.map((id) => active.get(id)).find(Boolean);
  const row = {
    id: a.github_advisory_id,
    cves: a.cves || [],
    module: a.module_name,
    severity: a.severity,
    vulnerable_versions: a.vulnerable_versions,
    patched_versions: a.patched_versions,
    url: a.url,
    paths: (a.findings || []).flatMap((f) => f.paths || []).slice(0, 3),
  };
  if (hit) { used.add(hit.id); suppressed.push({ ...row, allowlisted_by: hit.id, reason: hit.reason, expires: hit.expires }); }
  else failing.push(row);
}
const unused = [...active.keys()].filter((id) => !used.has(id));

console.log(JSON.stringify({
  level: LEVEL, today: TODAY,
  advisories: Object.keys(report.advisories).length, by_severity: bySeverity,
  failing: failing.length, suppressed: suppressed.length,
  expired: expired.length, unused_allowlist: unused,
  details: { failing, suppressed, expired },
}, null, 2));

for (const e of expired) console.error(`::error::pnpm-audit: allowlist entry ${e.id} expired on ${e.expires} (${e.reason})`);
for (const f of failing) console.error(`::error::pnpm-audit: ${f.severity} ${f.module} ${f.id} ${f.cves.join(",")} ${f.url}`);
for (const id of unused) console.warn(`::warning::pnpm-audit: allowlist entry ${id} no longer matches any advisory; remove it`);

if (failing.length || expired.length) process.exit(1);
console.log(`pnpm-audit: OK (${suppressed.length} allowlisted, threshold ${LEVEL})`);
NODE
}

# Advisories pip-audit may ignore, each with no fixed release and a reason it
# cannot reach us. Re-check on every release of the package; drop the line once
# a fixed version exists.
PIP_AUDIT_IGNORED=(
  # chromadb (1.5.9 is the latest release): all four are in chromadb's Python
  # server (FastAPI routes, SimpleRBACAuthorizationProvider, server-side
  # trust_remote_code). GAIA imports chromadb only as an HTTP client; the server
  # is the chromadb/chroma image, a single Rust binary with no Python in it.
  GHSA-f4j7-r4q5-qw2c
  GHSA-2wm9-hf6c-p5cr
  GHSA-xph7-9rjv-w5fr
  GHSA-36p7-vc44-83pf
  # wcmatch 10.1 (fix: 11.2), expires 2026-12-21. e2b <= 2.37.0 caps wcmatch<11 and
  # imports it only in the template builder (e2b/template/utils.py), reached only
  # from the operator script apps/api/scripts/build_e2b_template.py over our own
  # file names. Real fix: e2b >= 2.37.1 (PR #1862) with uv.lock on wcmatch >= 11.2;
  # drop this entry once the lock holds wcmatch >= 11.2.
  CVE-2026-132276
)

cmd_pip() {

  local ROOT ignore=() pip_exit
  ROOT="${PIP_AUDIT_ROOT:-$REPO_ROOT}"
  # $RUNNER_TEMP, not /tmp: twenty runner instances share the box's /tmp, and
  # two jobs from different PRs would audit each other's export.
  tmp="$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/pip-audit.XXXXXX")"
  trap 'rm -rf "$tmp"' EXIT

  (cd "$ROOT" && uv export --frozen --no-emit-workspace -o "$tmp/requirements.txt" > /dev/null)
  for id in "${PIP_AUDIT_IGNORED[@]}"; do ignore+=(--ignore-vuln "$id"); done
  # pip-audit exits 1 whenever it found anything; the verdict is decided below.
  set +e
  uv run --frozen --no-build --isolated --only-group lint pip-audit --strict --skip-editable --disable-pip "${ignore[@]}" \
    -r "$tmp/requirements.txt" -f json -o "$tmp/audit.json" 2> "$tmp/audit.err"
  pip_exit=$?
  set -e

  AUDIT_JSON="$tmp/audit.json" AUDIT_ERR="$tmp/audit.err" PIP_EXIT="$pip_exit" \
  python3 - <<'PY'
import json
import os
import sys
from pathlib import Path


def fail(message: str, code: int) -> None:
    print(f"::error::pip-audit: {message}", file=sys.stderr)
    raise SystemExit(code)


report_path = Path(os.environ["AUDIT_JSON"])
err = Path(os.environ["AUDIT_ERR"]).read_text().strip()
try:
    dependencies = json.loads(report_path.read_text())["dependencies"]
except (OSError, ValueError, KeyError) as exc:
    fail(f"pip-audit produced no usable report (exit {os.environ['PIP_EXIT']}): {exc}\n{err}", 2)

failing = [
    f"{dep['name']} {dep['version']} {vuln['id']} (fix: {', '.join(vuln.get('fix_versions') or []) or 'none'})"
    for dep in dependencies
    for vuln in dep.get("vulns", [])
]
for row in failing:
    print(f"::error::pip-audit: {row}")
if failing:
    print(f"pip-audit: {len(failing)} advisory(ies) to fix")
    raise SystemExit(1)
if os.environ["PIP_EXIT"] != "0":
    # --strict failures (a dependency it could not audit) leave no vulns at all.
    fail(f"pip-audit exited {os.environ['PIP_EXIT']} with no advisory to show for it:\n{err}", 2)
print("pip-audit: OK (no advisory outside PIP_AUDIT_IGNORED)")
PY
}

cmd_playwright_pin() {
  DOCKERFILE="$REPO_ROOT/apps/api/Dockerfile"

  fail=0
  check() {
    local pkg="$1" arg="$2" lock docker
    lock="$(awk -v n="name = \"$pkg\"" '$0==n{f=1} f && /^version = /{gsub(/"/,"",$3); print $3; exit}' "$REPO_ROOT/uv.lock")"
    docker="$(sed -nE "s/^ARG $arg=(.*)\$/\1/p" "$DOCKERFILE" | head -1)"
    if [ -z "$lock" ] || [ -z "$docker" ]; then
      echo "::error::could not read $pkg version (uv.lock='$lock', Dockerfile ARG $arg='$docker')"; fail=1; return
    fi
    if [ "$lock" != "$docker" ]; then
      echo "::error::$pkg pin drift: uv.lock has $lock, apps/api/Dockerfile ARG $arg=$docker"
      echo "Update the ARG so the browsers stage downloads the revision the runtime library expects."
      fail=1; return
    fi
    echo "$pkg pin OK ($lock)"
  }

  check playwright PLAYWRIGHT_VERSION
  exit "$fail"
}

cmd_model_pin() {
  DOCKERFILE="$REPO_ROOT/apps/api/Dockerfile"
  CONSTANTS="$REPO_ROOT/apps/api/app/constants/memory.py"

  fail=0
  check() {
    local constant="$1" arg="$2" code docker
    code="$(grep -E "^$constant = " "$CONSTANTS" | grep -oE '"[^"]+/[^"]+"' | tail -1 | tr -d '"')"
    docker="$(sed -nE "s/^ARG $arg=(.*)\$/\1/p" "$DOCKERFILE" | head -1)"
    if [ -z "$code" ] || [ -z "$docker" ]; then
      echo "::error::could not read $constant (memory.py='$code', Dockerfile ARG $arg='$docker')"; fail=1; return
    fi
    if [ "$code" != "$docker" ]; then
      echo "::error::baked model drift: $constant is $code, apps/api/Dockerfile ARG $arg=$docker"
      echo "Update the ARG and its revision so the image bakes the model the runtime loads."
      fail=1; return
    fi
    echo "$constant baked OK ($code)"
  }

  check EMBEDDING_MODEL_NAME EMBEDDING_MODEL
  check RERANKER_MODEL_NAME RERANKER_MODEL
  exit "$fail"
}

cmd_alert_rule_tools() {

  # shellcheck source=tools/alert-rules/tool-versions.env
  source "$(dirname "$0")/../../tools/alert-rules/tool-versions.env"

  BIN="${RUNNER_TEMP:?RUNNER_TEMP is required}/bin"
  WORK="$(mktemp -d "${RUNNER_TEMP}/alert-rule-tools.XXXXXX")"
  mkdir -p "$BIN"

  echo "::group::install"
  curl -sSL --proto '=https' -o "$WORK/pint.tar.gz" \
    "https://github.com/cloudflare/pint/releases/download/v${PINT_VERSION}/pint-${PINT_VERSION}-linux-amd64.tar.gz"
  tar -xzf "$WORK/pint.tar.gz" -C "$WORK"
  install -m 0755 "$WORK/pint-linux-amd64" "$BIN/pint"

  curl -sSL --proto '=https' -o "$WORK/prometheus.tar.gz" \
    "https://github.com/prometheus/prometheus/releases/download/v${PROMETHEUS_VERSION}/prometheus-${PROMETHEUS_VERSION}.linux-amd64.tar.gz"
  tar -xzf "$WORK/prometheus.tar.gz" -C "$WORK"
  install -m 0755 "$WORK/prometheus-${PROMETHEUS_VERSION}.linux-amd64/promtool" "$BIN/promtool"
  rm -rf "$WORK"
  echo "::endgroup::"

  echo "$BIN" >> "$GITHUB_PATH"
  echo "pint v${PINT_VERSION} + promtool v${PROMETHEUS_VERSION} installed in $BIN"
}

cmd_evlog() {

  # changes.sh owns the base: a branch, a remote ref or a merge group's sha.
  BASE_SHA=$(git merge-base "$(bash "$REPO_ROOT/scripts/ci/changes.sh" base-rev)" HEAD)
  # Scratch lives under the job's own temp dir, never a fixed /tmp name: /tmp
  # is sticky and shared by every user on a self-hosted box, so a file left
  # behind by another runner user is unwritable (EACCES) for this one.
  WORK=$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/evlog-ratchet.XXXXXX")
  # NB: keep the worktree dir name free of sensitivity terms ("checkout",
  # "auth", ...) — it prefixes every base file path. The trap cleans the
  # worktree up even on failure so a re-run never trips over a stale
  # registration.
  BASE_DIR="$WORK/obs-merge-base"
  trap 'rm -rf "$WORK"; git worktree prune' EXIT
  git worktree add --detach "$BASE_DIR" "$BASE_SHA"

  # Same merge-base diff + ACMR filter as `changes.sh files`, plus -M and
  # --name-status to see the old path of each rename.
  : > "$WORK"/head-files.txt
  : > "$WORK"/base-files.txt
  : > "$WORK"/renames.txt
  while IFS=$'\t' read -r status p1 p2; do
    case "$status" in
      R*)
        head_path="$p2"
        base_path="$p1"
        ;;
      *)
        head_path="$p1"
        base_path="$p1"
        ;;
    esac
    case "$head_path" in
      *.py) ;;
      *) continue ;;
    esac
    if [ -f "$head_path" ]; then
      echo "$head_path" >> "$WORK"/head-files.txt
    fi
    if [ -f "$BASE_DIR/$base_path" ]; then
      echo "$BASE_DIR/$base_path" >> "$WORK"/base-files.txt
      if [ "$base_path" != "$head_path" ]; then
        printf '%s\t%s\n' "$base_path" "$head_path" >> "$WORK"/renames.txt
      fi
    fi
  done < <(git diff --name-status -M --diff-filter=ACMR "$BASE_SHA"...HEAD)

  if [ ! -s "$WORK"/head-files.txt ]; then
    ci_ok "observability: OK (no changed Python files to ratchet)"
    return 0
  fi
  python3 tools/evlog_map --files-from "$WORK"/base-files.txt --json --no-write > "$WORK"/base-map.json
  python3 tools/evlog_map --files-from "$WORK"/head-files.txt --no-write \
    --baseline "$WORK"/base-map.json --rename-map "$WORK"/renames.txt
}

cmd_uv_lock() {
  local root="${UV_LOCK_ROOT:-$REPO_ROOT}" locks dir checked=0
  local stale=()
  locks=$(git -C "$root" ls-files -- ':(glob)**/uv.lock')
  [ -n "$locks" ] || ci_die "uv-lock: no tracked uv.lock under $root"

  while read -r lock; do
    dir=$(dirname "$lock")
    ci_group "uv lock --check ($dir)"
    if ! uv lock --check --project "$root/$dir"; then
      stale+=("$dir")
    fi
    ci_endgroup
    checked=$((checked + 1))
  done <<< "$locks"

  if [ "${#stale[@]}" -gt 0 ]; then
    ci_die "uv-lock: ${stale[*]}: uv.lock no longer resolves from pyproject.toml; run 'uv lock' there"
  fi
  ci_ok "uv-lock: OK ($checked lockfiles current)"
}

# The gitleaks CLI the secrets check runs, by its release tarball's sha256.
GITLEAKS_VERSION=8.24.3
gitleaks_sha256() {
  case "$1" in
    linux_x64) echo 9991e0b2903da4c8f6122b5c3186448b927a5da4deef1fe45271c3793f4ee29c ;;
    linux_arm64) echo 5f2edbe1f49f7b920f9e06e90759947d3c5dfc16f752fb93aaafc17e9d14cf07 ;;
    darwin_x64) echo 41c44ae8ad1d6eef57d4526ad0fd67d8129eee9a856f55c2b3b9395fd3d9ec0f ;;
    darwin_arm64) echo b90f13bb8c90ab72083d9b0c842e39dafb82c0e5c3f872f407366b7a58909013 ;;
    *) ci_die "secrets: gitleaks $GITLEAKS_VERSION has no pinned build for $1" ;;
  esac
}

# Extract the pinned gitleaks into <dir>. Only the release tarball is cached, and it is
# checked against its pin on every run: the box's cache outlives the job that wrote it.
install_gitleaks() {
  local dir="$1" os arch want url cache tarball
  case "$(uname -s)" in
    Linux) os=linux ;;
    Darwin) os=darwin ;;
    *) ci_die "secrets: no gitleaks build for $(uname -s)" ;;
  esac
  case "$(uname -m)" in
    x86_64 | amd64) arch=x64 ;;
    aarch64 | arm64) arch=arm64 ;;
    *) ci_die "secrets: no gitleaks build for $(uname -m)" ;;
  esac
  want="${GITLEAKS_SHA256:-$(gitleaks_sha256 "${os}_${arch}")}"
  url="${GITLEAKS_RELEASE_URL:-https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_${os}_${arch}.tar.gz}"
  cache="${GITLEAKS_CACHE:-${RUNNER_TOOL_CACHE:-$HOME/.cache}/gitleaks}"
  tarball="$cache/gitleaks_${GITLEAKS_VERSION}_${os}_${arch}.tar.gz"
  if ! { [ -f "$tarball" ] && digest_matches sha256 "$want" "$tarball"; }; then
    mkdir -p "$cache"
    fetch_verified "gitleaks $GITLEAKS_VERSION (${os}_${arch})" "$url" sha256 "$want" "$dir/gitleaks.tar.gz"
    mv -f "$dir/gitleaks.tar.gz" "$tarball"
  fi
  tar -xzf "$tarball" -C "$dir" gitleaks
}

# Every commit the change adds, merged-in branches included: no --first-parent,
# which hid a fixture key a merged branch brought into #1723 until the master push.
secrets_range() {
  local root="$1" base
  if [[ "${GITHUB_EVENT_NAME:-}" == "push" ]]; then
    base="${PUSH_BEFORE_SHA:-}"
    [[ "$base" =~ ^[0-9a-f]{40}$ && "$base" != "0000000000000000000000000000000000000000" ]] \
      || ci_die "secrets: a push needs PUSH_BEFORE_SHA, the commit the push moved from (got '${base}')"
  else
    base="$(cd "$root" && bash "$REPO_ROOT/scripts/ci/changes.sh" base-rev)"
  fi
  echo "${base}..HEAD"
}

cmd_secrets() {
  local lane=""
  if [[ "${1:-}" == "--lane" ]]; then
    lane="${2:?secrets --lane needs a lane id}"
  fi
  [ -n "$lane" ] || ci_die "secrets: --lane <job>/<check> is required"

  local root="${SECRETS_ROOT:-$REPO_ROOT}" range commits work sarif status=0
  range="$(secrets_range "$root")"
  commits="$(git -C "$root" rev-list --count "$range")"
  work="$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/gitleaks.XXXXXX")"
  # shellcheck disable=SC2064 # expand now: work is local to this function
  trap "rm -rf '$work'" EXIT
  sarif="$work/gitleaks.sarif"
  install_gitleaks "$work"

  ci_group "gitleaks $GITLEAKS_VERSION over $range ($commits commits)"
  "$work/gitleaks" detect --source "$root" --config "$root/.gitleaks.toml" \
    --gitleaks-ignore-path "$root/.gitleaksignore" --log-opts="$range" \
    --redact --verbose --no-banner --exit-code=2 \
    --report-format=sarif --report-path="$sarif" || status=$?
  ci_endgroup

  case "$status" in
    0) ci_ok "gitleaks: OK ($commits commits in $range clean)" ;;
    2)
      python3 "$REPO_ROOT/scripts/ci/verdict.py" sarif --lane "$lane" "$sarif"
      ci_die "gitleaks: secrets found in $range (findings above); allowlist a fixture by exact value in .gitleaks.toml"
      ;;
    *) ci_die "gitleaks: the scan itself failed (exit $status)" ;;
  esac
}

usage() {
  sed -n '2,22p' "$0" >&2
}

main() {
  local sub="${1:-}"
  shift || true
  case "$sub" in
    pnpm)             cmd_pnpm "$@" ;;
    pip)              cmd_pip "$@" ;;
    playwright-pin)   cmd_playwright_pin "$@" ;;
    model-pin)        cmd_model_pin "$@" ;;
    alert-rule-tools) cmd_alert_rule_tools "$@" ;;
    evlog)            cmd_evlog "$@" ;;
    uv-lock)          cmd_uv_lock "$@" ;;
    secrets)          cmd_secrets "$@" ;;
    *)
      echo "audit.sh: unknown subcommand '${sub}'" >&2
      usage
      exit 2
      ;;
  esac
}

main "$@"
