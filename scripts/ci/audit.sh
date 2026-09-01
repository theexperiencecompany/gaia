#!/usr/bin/env bash
# audit.sh — the standing checks on what we depend on and what we emit.
#
# Subcommands:
#   pnpm               Fail-loud `pnpm audit` gate for the JS workspace, with
#                      an allowlist that requires an owner, a reason and an
#                      expiry (an expired entry fails).
#   playwright-pin     apps/api/Dockerfile's PLAYWRIGHT_VERSION and
#                      PATCHRIGHT_VERSION must equal the versions in uv.lock.
#   alert-rule-tools   Install pinned pint + promtool for the alert-rules lane
#                      into $RUNNER_TEMP/bin and prepend it to $GITHUB_PATH.
#   evlog              Per-file observability ratchet over the changed Python
#                      files: a file whose score dropped fails the lane.
#
# Env contract:
#   pnpm              PNPM_AUDIT_LEVEL (high), PNPM_AUDIT_ALLOWLIST
#                     (config/pnpm-audit-allowlist.json), PNPM_AUDIT_TODAY
#                     (tests), PNPM_AUDIT_ROOT (tests).
#                     Exit: 0 clean / all allowlisted; 1 findings or expired
#                     entries; 2 the audit itself could not run.
#   playwright-pin    none.
#   alert-rule-tools  RUNNER_TEMP (required), GITHUB_PATH.
#   evlog             GITHUB_BASE_REF (required), RUNNER_TEMP; needs a
#                     fetch-depth: 0 checkout.
set -euo pipefail

# shellcheck source=scripts/ci/lib/log.sh
source "$(dirname "$0")/lib/log.sh"

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
  failing: failing.length, suppressed: suppressed.length, expired: expired.length, unused_allowlist: unused,
  details: { failing, suppressed, expired },
}, null, 2));

for (const e of expired) console.error(`::error::pnpm-audit: allowlist entry ${e.id} expired on ${e.expires} (${e.reason})`);
for (const f of failing) console.error(`::error::pnpm-audit: ${f.severity} ${f.module} ${f.id} ${f.cves.join(",")} ${f.url}`);
for (const id of unused) console.warn(`::warning::pnpm-audit: allowlist entry ${id} no longer matches any advisory; remove it`);

if (failing.length || expired.length) process.exit(1);
console.log(`pnpm-audit: OK (${suppressed.length} allowlisted, threshold ${LEVEL})`);
NODE
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
  check patchright PATCHRIGHT_VERSION
  exit "$fail"
}

cmd_alert_rule_tools() {

  PINT_VERSION="0.87.0"
  PROMETHEUS_VERSION="3.1.0"

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

  BASE_SHA=$(git merge-base "origin/$GITHUB_BASE_REF" HEAD)
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

  python3 tools/evlog_map --files-from "$WORK"/base-files.txt --json --no-write > "$WORK"/base-map.json
  python3 tools/evlog_map --files-from "$WORK"/head-files.txt --no-write \
    --baseline "$WORK"/base-map.json --rename-map "$WORK"/renames.txt
}

usage() {
  sed -n '2,14p' "$0" >&2
}

main() {
  local sub="${1:-}"
  shift || true
  case "$sub" in
    pnpm)             cmd_pnpm "$@" ;;
    playwright-pin)   cmd_playwright_pin "$@" ;;
    alert-rule-tools) cmd_alert_rule_tools "$@" ;;
    evlog)            cmd_evlog "$@" ;;
    *)
      echo "audit.sh: unknown subcommand '${sub}'" >&2
      usage
      exit 2
      ;;
  esac
}

main "$@"
