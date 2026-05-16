#!/usr/bin/env node
/**
 * File size gate.
 *
 * Default mode: print a report of files exceeding their target limit, but
 * only EXIT NON-ZERO when a file blows the hard cap (1200 lines) AND isn't
 * in NO_HARD_CAP_PATTERNS. That makes it a tech-debt ratchet: existing
 * monsters surface, anything new gets blocked at 1200 lines, and the
 * stricter default (400) lights up in the report for follow-up cleanup.
 *
 * --enforce-all  → fail on any file exceeding its limit (full strictness).
 * --quiet        → suppress the report; only emit on failure.
 */
import { readFileSync } from "node:fs";
import { execFileSync } from "node:child_process";

const DEFAULT_LIMIT = 400;
const RELAXED_LIMIT = 700;
const HARD_LIMIT = 1200;

const RELAXED_PATTERNS = [
  /\/registries\//,
  /openui\/components\//,
  /\.stories\.tsx$/,
  /tokenizer\.ts$/,
];

const NO_HARD_CAP_PATTERNS = [
  /\/data\//,
  /\.generated\./,
  /fixtures\.ts$/,
  /iconPaths\.generated\.ts$/,
  /openui\/components\//,
  /\/combosData-/,
  /apps\/web\/src\/components\/ui\/map\.tsx$/,
  /packages\/cli\/src\/ui\/screens\//,
  /apps\/web\/src\/app\/.+\/dev\//,
  /apps\/web\/src\/features\/landing\/components\/iphone\//,
  /apps\/web\/src\/features\/landing\/constants\//,
  /apps\/mobile\/src\/features\/chat\/components\/sidebar\//,
  /__tests__\//,
];

const IGNORE_PATTERNS = [
  /\/node_modules\//,
  /\/\.next\//,
  /\/\.nx\//,
  /\/\.turbo\//,
  /\/dist\//,
  /\/out\//,
  /\/build\//,
  /\/coverage\//,
  /\/\.venv\//,
  /\/__pycache__\//,
  /\.d\.ts$/,
  /\.snap$/,
  /apps\/web\/public\//,
  /apps\/web\/content\//,
  /apps\/api\//,
  /apps\/voice-agent\//,
  /infra\//,
  /docs\//,
  /\.agents\//,
  /\.claude\//,
];

const shouldIgnore = (p) => IGNORE_PATTERNS.some((rx) => rx.test(p));
const limitFor = (p) =>
  NO_HARD_CAP_PATTERNS.some((rx) => rx.test(p)) ||
  RELAXED_PATTERNS.some((rx) => rx.test(p))
    ? RELAXED_LIMIT
    : DEFAULT_LIMIT;
const exemptFromHardCap = (p) =>
  NO_HARD_CAP_PATTERNS.some((rx) => rx.test(p));

function getFiles() {
  // `git` is intentionally resolved via PATH; CI runners always have it.
  const out = execFileSync( // NOSONAR javascript:S4036
    "git", // NOSONAR javascript:S4036
    [
      "ls-files",
      "*.ts",
      "*.tsx",
      "*.js",
      "*.jsx",
      "*.mjs",
      "*.cjs",
    ],
    { encoding: "utf8" },
  );
  return out
    .trim()
    .split("\n")
    .filter(Boolean)
    .filter((p) => !shouldIgnore(p));
}

const countLines = (p) => readFileSync(p, "utf8").split("\n").length;

const args = new Set(process.argv.slice(2));
const enforceAll = args.has("--enforce-all");
const quiet = args.has("--quiet");

const offenders = [];
const hardOffenders = [];

for (const file of getFiles()) {
  const lines = countLines(file);
  const limit = limitFor(file);
  if (lines > HARD_LIMIT && !exemptFromHardCap(file)) {
    hardOffenders.push({ file, lines, limit });
  } else if (lines > limit) {
    offenders.push({ file, lines, limit });
  }
}

const fmt = (rows) =>
  rows
    .sort((a, b) => b.lines - a.lines)
    .map((r) => `  ${r.lines.toString().padStart(5)} / ${r.limit}  ${r.file}`)
    .join("\n");

if (!quiet) {
  console.log("");
  console.log("File size report");
  console.log("════════════════════════════════════════════════════════");
  console.log(
    `Default: ${DEFAULT_LIMIT} | Relaxed: ${RELAXED_LIMIT} | Hard cap: ${HARD_LIMIT}`,
  );
  console.log("");
  if (hardOffenders.length) {
    console.log(`HARD CAP VIOLATIONS (${hardOffenders.length}):`);
    console.log(fmt(hardOffenders));
    console.log("");
  }
  if (offenders.length) {
    console.log(`Over limit (informational, ${offenders.length}):`);
    console.log(fmt(offenders));
    console.log("");
  }
  if (!offenders.length && !hardOffenders.length) {
    console.log("✓ All files within size limits.");
  }
}

if (hardOffenders.length) {
  console.error(
    `\n❌ ${hardOffenders.length} file(s) exceed the hard cap of ${HARD_LIMIT} lines. Split before merging.`,
  );
  process.exit(1);
}
if (enforceAll && offenders.length) {
  console.error(
    `\n❌ ${offenders.length} file(s) exceed their size limit. Split or move logic to focused modules.`,
  );
  process.exit(1);
}
