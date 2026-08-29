#!/usr/bin/env bash
# pnpm-audit.sh — fail-loud `pnpm audit` gate for the JS workspace.
#
# Why a wrapper and not `pnpm audit --audit-level=high` directly:
#   * pnpm's own `--ignore <cve>` is a bare list with no owner, reason or
#     expiry, so exceptions silently outlive the reason they were added.
#     config/pnpm-audit-allowlist.json requires all three and an expired
#     entry FAILS the run (exit 1) until it is renewed or removed.
#   * pnpm exits 1 on any finding regardless of level in --json mode, and
#     exits 1 on a registry outage too, so "no output" and "vulnerable" look
#     the same. We parse the JSON ourselves and treat unparsable output as a
#     hard error (exit 2), never as a pass.
#   * Prints a one-block JSON summary so the CI log shows what was gated,
#     what was suppressed and why.
#
# Usage: scripts/ci/pnpm-audit.sh
# Env:   PNPM_AUDIT_LEVEL     low|moderate|high|critical   (default: high)
#        PNPM_AUDIT_ALLOWLIST path to allowlist json        (default: config/pnpm-audit-allowlist.json)
#        PNPM_AUDIT_TODAY     YYYY-MM-DD, overrides the clock (tests)
# Exit:  0 clean / all findings allowlisted; 1 findings or expired entries;
#        2 the audit itself could not run (registry, malformed allowlist).
set -euo pipefail

ROOT="${PNPM_AUDIT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
ALLOWLIST="${PNPM_AUDIT_ALLOWLIST:-$ROOT/config/pnpm-audit-allowlist.json}"
LEVEL="${PNPM_AUDIT_LEVEL:-high}"
TODAY="${PNPM_AUDIT_TODAY:-$(date -u +%Y-%m-%d)}"

if [ ! -f "$ALLOWLIST" ]; then
  echo "::error::pnpm-audit: allowlist not found at $ALLOWLIST" >&2
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
