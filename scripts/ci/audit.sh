#!/usr/bin/env bash
# audit.sh — the standing checks on what we depend on and what we emit.
#
# Subcommands:
#   pnpm               Fail-loud `pnpm audit` gate for the JS workspace, with
#                      an allowlist that requires an owner, a reason and an
#                      expiry (an expired entry fails).
#   pip                Fail-loud `pip-audit` gate over the uv.lock export.
#   playwright-pin     apps/api/Dockerfile's PLAYWRIGHT_VERSION and
#                      PATCHRIGHT_VERSION must equal the versions in uv.lock.
#   alert-rule-tools   Install pinned pint + promtool for the alert-rules lane
#                      into $RUNNER_TEMP/bin and prepend it to $GITHUB_PATH.
#   evlog              Per-file observability ratchet over the changed Python
#                      files: a file whose score dropped fails the lane.
#   uv-lock            Every tracked uv.lock must still resolve from its
#                      pyproject.toml (`uv lock --check`), standalone projects
#                      outside the root workspace included.
#
# Both audits take AUDIT_SCOPE. `all` (master, dispatch) fails on any
# advisory. `introduced` (a PR push, the merge queue) fails only on an advisory
# in a package version the change itself put in the lockfile — one absent from
# the lockfile at the merge-base with the base (`changes.sh base-rev`). An
# advisory published against a version the base already ships reds master,
# where it belongs, and is a ::warning:: on the PR: the PR did not cause it and
# could not fix it without a bump that does not belong in it (CLAUDE.md §9).
#
# Env contract:
#   pnpm              AUDIT_SCOPE (all), PNPM_AUDIT_LEVEL (high),
#                     PNPM_AUDIT_ALLOWLIST (config/pnpm-audit-allowlist.json),
#                     PNPM_AUDIT_TODAY (tests), PNPM_AUDIT_ROOT (tests),
#                     GAIA_PR_BASE (introduced scope).
#                     Exit: 0 clean / all allowlisted; 1 findings or expired
#                     entries; 2 the audit itself could not run.
#   pip               AUDIT_SCOPE (all), PIP_AUDIT_ROOT (tests), GAIA_PR_BASE
#                     (introduced scope), RUNNER_TEMP. Exit codes as pnpm's.
#   playwright-pin    none.
#   alert-rule-tools  RUNNER_TEMP (required), GITHUB_PATH.
#   evlog             GAIA_PR_BASE or GITHUB_BASE_REF (optional; falls back to
#                     NX_BASE/master locally), RUNNER_TEMP; needs a fetch-depth: 0
#                     checkout.
#   uv-lock           UV_LOCK_ROOT (tests; defaults to the repo root). Needs uv
#                     and index access. Exit: 0 all current; 1 any stale lock.
set -euo pipefail

# shellcheck source=scripts/ci/lib/log.sh
source "$(dirname "$0")/lib/log.sh"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# The scope an audit runs at, validated: anything but the two values is a typo
# that would silently pick one of them.
_audit_scope() {
  local scope="${AUDIT_SCOPE:-all}"
  case "$scope" in
    all|introduced) printf '%s' "$scope" ;;
    *) echo "::error::audit: AUDIT_SCOPE must be all or introduced, got '$scope'" >&2; exit 2 ;;
  esac
}

# Write <lockfile> as it stood at the merge-base with the change's base to <out>.
# A base that cannot be resolved is exit 2: comparing against nothing would call
# every advisory introduced, or none.
_base_lockfile() {
  local root="$1" lockfile="$2" out="$3" rev merge_base
  rev="$(cd "$root" && bash "$REPO_ROOT/scripts/ci/changes.sh" base-rev)" || exit 2
  merge_base="$(git -C "$root" merge-base "$rev" HEAD)" || {
    echo "::error::audit: no merge-base between $rev and HEAD" >&2
    exit 2
  }
  if ! git -C "$root" show "$merge_base:$lockfile" > "$out" 2> /dev/null; then
    # A lockfile the base does not have at all: every version in it is new.
    : > "$out"
  fi
}

cmd_pnpm() {

  ROOT="${PNPM_AUDIT_ROOT:-$REPO_ROOT}"
  SCOPE="$(_audit_scope)"
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

  BASE_LOCK=""
  if [ "$SCOPE" = "introduced" ]; then
    BASE_LOCK="$tmp/base-pnpm-lock.yaml"
    _base_lockfile "$ROOT" pnpm-lock.yaml "$BASE_LOCK"
  fi

  AUDIT_JSON="$tmp/audit.json" AUDIT_ERR="$tmp/audit.err" PNPM_EXIT="$pnpm_exit" \
  ALLOWLIST="$ALLOWLIST" LEVEL="$LEVEL" TODAY="$TODAY" BASE_LOCK="$BASE_LOCK" node - <<'NODE'
const fs = require("node:fs");
const { AUDIT_JSON, AUDIT_ERR, PNPM_EXIT, ALLOWLIST, LEVEL, TODAY, BASE_LOCK } = process.env;
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

// Every `name@version` the base lockfile resolves: the keys of its `packages:`
// section ('@scope/name@1.2.3': or name@1.2.3:). The overrides and importers
// sections sit at the same indent and are not packages, so only that section counts.
const baseVersions = (() => {
  if (!BASE_LOCK) return null;
  const seen = new Set();
  let inPackages = false;
  for (const line of fs.readFileSync(BASE_LOCK, "utf8").split("\n")) {
    if (/^\S/.test(line)) inPackages = line === "packages:";
    const key = inPackages && line.match(/^  '?([^\s']+?)'?:$/);
    if (key) seen.add(key[1]);
  }
  return seen;
})();
const introduced = (a) =>
  baseVersions === null ||
  (a.findings || []).some((f) => !baseVersions.has(`${a.module_name}@${f.version}`));

const expired = allow.filter((e) => e.expires < TODAY);
const active = new Map(allow.filter((e) => e.expires >= TODAY).map((e) => [e.id, e]));
const used = new Set();

const bySeverity = { low: 0, moderate: 0, high: 0, critical: 0 };
const failing = [];
const suppressed = [];
const preexisting = [];
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
  else if (introduced(a)) failing.push(row);
  else preexisting.push(row);
}
const unused = [...active.keys()].filter((id) => !used.has(id));

console.log(JSON.stringify({
  level: LEVEL, today: TODAY,
  advisories: Object.keys(report.advisories).length, by_severity: bySeverity,
  scope: baseVersions === null ? "all" : "introduced",
  failing: failing.length, suppressed: suppressed.length, preexisting: preexisting.length,
  expired: expired.length, unused_allowlist: unused,
  details: { failing, suppressed, preexisting, expired },
}, null, 2));

for (const e of expired) console.error(`::error::pnpm-audit: allowlist entry ${e.id} expired on ${e.expires} (${e.reason})`);
for (const f of failing) console.error(`::error::pnpm-audit: ${f.severity} ${f.module} ${f.id} ${f.cves.join(",")} ${f.url}`);
for (const f of preexisting) console.warn(`::warning::pnpm-audit: ${f.severity} ${f.module} ${f.id} is in a version the base already ships — not this change's to fix; master fails on it ${f.url}`);
for (const id of unused) console.warn(`::warning::pnpm-audit: allowlist entry ${id} no longer matches any advisory; remove it`);

if (failing.length || expired.length) process.exit(1);
console.log(`pnpm-audit: OK (${suppressed.length} allowlisted, threshold ${LEVEL})`);
NODE
}

# Advisories pip-audit may ignore, each with no fixed release and a reason it
# cannot reach us. Re-check on every release of the package; drop the line once
# a fixed version exists.
PIP_AUDIT_IGNORED=(
  # ecdsa: side-channel timing attack, out of the project's own scope upstream.
  GHSA-wj6h-64fc-37mp
  PYSEC-2026-1325
  # python-jose HMAC key confusion (3.5.0 is the latest release): every
  # jose.jwt.decode call site passes an explicit algorithms=[HS256], which is
  # exactly the precondition the advisory requires to be absent.
  GHSA-3qf3-8w2g-rqmx
)

cmd_pip() {

  local ROOT SCOPE ignore=() pip_exit base_lock=""
  ROOT="${PIP_AUDIT_ROOT:-$REPO_ROOT}"
  SCOPE="$(_audit_scope)"
  # $RUNNER_TEMP, not /tmp: twenty runner instances share the box's /tmp, and
  # two jobs from different PRs would audit each other's export.
  tmp="$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/pip-audit.XXXXXX")"
  trap 'rm -rf "$tmp"' EXIT

  (cd "$ROOT" && uv export --frozen --no-emit-workspace -o "$tmp/requirements.txt" > /dev/null)
  for id in "${PIP_AUDIT_IGNORED[@]}"; do ignore+=(--ignore-vuln "$id"); done
  # pip-audit exits 1 whenever it found anything; the verdict is decided below.
  set +e
  uvx --no-build pip-audit==2.10.1 --strict --skip-editable --disable-pip "${ignore[@]}" \
    -r "$tmp/requirements.txt" -f json -o "$tmp/audit.json" 2> "$tmp/audit.err"
  pip_exit=$?
  set -e

  if [ "$SCOPE" = "introduced" ]; then
    base_lock="$tmp/base-uv.lock"
    _base_lockfile "$ROOT" uv.lock "$base_lock"
  fi

  AUDIT_JSON="$tmp/audit.json" AUDIT_ERR="$tmp/audit.err" PIP_EXIT="$pip_exit" \
  BASE_LOCK="$base_lock" python3 - <<'PY'
import json
import os
import re
import sys
import tomllib
from pathlib import Path


def norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def fail(message: str, code: int) -> None:
    print(f"::error::pip-audit: {message}", file=sys.stderr)
    raise SystemExit(code)


report_path = Path(os.environ["AUDIT_JSON"])
err = Path(os.environ["AUDIT_ERR"]).read_text().strip()
try:
    dependencies = json.loads(report_path.read_text())["dependencies"]
except (OSError, ValueError, KeyError) as exc:
    fail(f"pip-audit produced no usable report (exit {os.environ['PIP_EXIT']}): {exc}\n{err}", 2)

base_lock = os.environ["BASE_LOCK"]
base: set[tuple[str, str]] | None = None
if base_lock:
    text = Path(base_lock).read_text()
    packages = tomllib.loads(text).get("package", []) if text else []
    base = {(norm(p["name"]), str(p.get("version", ""))) for p in packages}

failing, preexisting = [], []
for dep in dependencies:
    for vuln in dep.get("vulns", []):
        row = f"{dep['name']} {dep['version']} {vuln['id']} (fix: {', '.join(vuln.get('fix_versions') or []) or 'none'})"
        new = base is None or (norm(dep["name"]), str(dep["version"])) not in base
        (failing if new else preexisting).append(row)

for row in failing:
    print(f"::error::pip-audit: {row}")
for row in preexisting:
    print(f"::warning::pip-audit: {row} is in a version the base already ships — not this change's to fix; master fails on it")
if failing:
    print(f"pip-audit: {len(failing)} advisory(ies) to fix, {len(preexisting)} pre-existing")
    raise SystemExit(1)
if os.environ["PIP_EXIT"] != "0" and not preexisting:
    # --strict failures (a dependency it could not audit) leave no vulns at all.
    fail(f"pip-audit exited {os.environ['PIP_EXIT']} with no advisory to show for it:\n{err}", 2)
print(f"pip-audit: OK ({len(preexisting)} pre-existing advisory(ies) warned, scope {'introduced' if base is not None else 'all'})")
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

  # GAIA_PR_BASE first: on a stacked PR the event payload names the stack's
  # trunk, so this ratchet would compare against the bottom of the stack and
  # demand a score for every file the PRs below it touched. See the note at the
  # top of changes.sh. CI sets GITHUB_BASE_REF; local runs (`mise ci:local`) do
  # not, so mirror changes.sh's fallback (NX_BASE, then master) to keep the lane
  # runnable locally instead of dying on an unbound variable under `set -u`.
  NX_BASE_REF="${NX_BASE:-}"
  BASE_REF="${GAIA_PR_BASE:-${GITHUB_BASE_REF:-${NX_BASE_REF#origin/}}}"
  BASE_REF="${BASE_REF:-master}"
  BASE_SHA=$(git merge-base "origin/$BASE_REF" HEAD)
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

usage() {
  sed -n '2,17p' "$0" >&2
}

main() {
  local sub="${1:-}"
  shift || true
  case "$sub" in
    pnpm)             cmd_pnpm "$@" ;;
    pip)              cmd_pip "$@" ;;
    playwright-pin)   cmd_playwright_pin "$@" ;;
    alert-rule-tools) cmd_alert_rule_tools "$@" ;;
    evlog)            cmd_evlog "$@" ;;
    uv-lock)          cmd_uv_lock "$@" ;;
    *)
      echo "audit.sh: unknown subcommand '${sub}'" >&2
      usage
      exit 2
      ;;
  esac
}

main "$@"
