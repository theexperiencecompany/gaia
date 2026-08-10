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
import { explicitFileList } from "./lib/explicit-file-list.mjs";

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

const SCANNED_EXTENSIONS = [".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"];

function getFiles() {
  const explicit = explicitFileList();
  if (explicit.length > 0) {
    return explicit
      .filter((p) => SCANNED_EXTENSIONS.some((ext) => p.endsWith(ext)))
      .filter((p) => !shouldIgnore(p));
  }
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
    `\n❌ file-size gate FAILED — ${hardOffenders.length} file(s) exceed the hard cap of ${HARD_LIMIT} lines.`,
  );
  console.error(
    "\nWhy: a file that keeps growing accumulates unrelated responsibilities" +
      " until no one can hold it in their head, review it, or change it safely.",
  );
  console.error(
    `\nOffending files (lines / per-file target; hard cap is ${HARD_LIMIT}):`,
  );
  console.error(fmt(hardOffenders));
  console.error(
    "\nFix: split each file above by responsibility — move each distinct concern" +
      " into its own focused module (a React component into its own file, a hook" +
      " into a `hooks/` dir, types into a `*.types.ts`). Do NOT raise HARD_LIMIT or" +
      " add a NO_HARD_CAP_PATTERNS entry to get past this — that hides the debt.",
  );
  console.error(
    '\nRule: .claude/rules/general.md § "File Size & Single Responsibility"' +
      " (a file that does two things should be two files).",
  );
  process.exit(1);
}
if (enforceAll && offenders.length) {
  console.error(
    `\n❌ file-size gate FAILED — ${offenders.length} file(s) exceed their per-file limit (default ${DEFAULT_LIMIT}, relaxed ${RELAXED_LIMIT}).`,
  );
  console.error(
    "\nWhy: oversized files mix concerns and are hard to review, test, and delete.",
  );
  console.error("\nOffending files (lines / limit):");
  console.error(fmt(offenders));
  console.error(
    "\nFix: split each file above by responsibility into focused modules." +
      " Do NOT bump the limit to pass.",
  );
  console.error(
    '\nRule: .claude/rules/general.md § "File Size & Single Responsibility".',
  );
  process.exit(1);
}
