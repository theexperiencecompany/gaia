#!/usr/bin/env node
/**
 * checks.mjs — the static hygiene gates over the TypeScript/JS surface.
 *
 * Subcommands:
 *   file-sizes [--enforce-all] [--quiet]
 *                       File size gate. Default mode reports every file over
 *                       its target limit but only FAILS on the 1200-line hard
 *                       cap, so existing monsters surface while anything new
 *                       is blocked. --enforce-all fails on any file over its
 *                       limit; --quiet suppresses the report.
 *   components-per-file Fail when a .tsx file exports more than 2 React
 *                       components.
 *   types-location [--enforce|--strict]
 *                       Fail (or, without the flag, report) when a non-type
 *                       file exports more than 3 types.
 *   duplication         Fail when more than 3% of the lines this branch ADDS
 *                       sit inside a copy-pasted block (the SonarCloud
 *                       denominator, reproduced with jscpd).
 *   evlog-map-bots [--json] [--min-score N] [--min-entries N] [--files-from F]
 *                       Observability score for the bots' wide-event entry
 *                       points. Implementation in lib/evlog-map-bots.mjs.
 *   api-schema [--write]
 *                       Regenerate apps/api/openapi.json and the TypeScript
 *                       types in libs/shared/ts/src/api/generated, then fail
 *                       if either differs from what is committed. --write
 *                       regenerates without checking (what `mise api:types`
 *                       runs).
 *   api-schema-types    Fail when a .ts/.tsx file outside the generated dir
 *                       hand-writes a type that mirrors an API model, or when
 *                       web feature code calls the untyped `apiService`
 *                       declares an interface/type named after an
 *                       openapi.json component schema — the hand-written
 *                       twin of a Pydantic model. `type X = Schema<"X">` is
 *                       the one allowed form.
 *
 * Env contract: CHANGED_FILES (see lib/explicit-file-list.mjs) scopes the
 * file-walking gates to a lane's changed files; empty means full scan.
 * `duplication` reads GAIA_PR_BASE, then GITHUB_BASE_REF, for its diff base
 * (default master).
 */
import { execFileSync, execSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { explicitFileList } from "./lib/explicit-file-list.mjs";
import { runEvlogMapBots } from "./lib/evlog-map-bots.mjs";

// ---------------------------------------------------------------------------
// file-sizes
// ---------------------------------------------------------------------------

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

// `git` is intentionally resolved via PATH; CI runners always have it.
const gitLsFiles = (patterns) =>
  execFileSync( // NOSONAR javascript:S4036
    "git", // NOSONAR javascript:S4036
    ["ls-files", ...patterns],
    { encoding: "utf8" },
  )
    .trim()
    .split("\n")
    .filter(Boolean);

function sizeFiles(args) {
  const explicit = explicitFileList(args);
  if (explicit.length > 0) {
    return explicit
      .filter((p) => SCANNED_EXTENSIONS.some((ext) => p.endsWith(ext)))
      .filter((p) => !shouldIgnore(p));
  }
  return gitLsFiles([
    "*.ts",
    "*.tsx",
    "*.js",
    "*.jsx",
    "*.mjs",
    "*.cjs",
  ]).filter((p) => !shouldIgnore(p));
}

const countLines = (p) => readFileSync(p, "utf8").split("\n").length;

function cmdFileSizes(argv) {
  const args = new Set(argv);
  const enforceAll = args.has("--enforce-all");
  const quiet = args.has("--quiet");

  const offenders = [];
  const hardOffenders = [];

  for (const file of sizeFiles(argv)) {
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
}

// ---------------------------------------------------------------------------
// components-per-file
// ---------------------------------------------------------------------------

const COMPONENT_ALLOWLIST_PREFIXES = [
  "apps/web/src/components/ui/",
  "apps/web/src/config/openui/components/",
  "apps/web/src/features/landing/components/demo/",
  "apps/web/content/",
  "apps/web/src/lib/",
  "apps/mobile/src/config/openui/components/",
];

const COMPONENT_ALLOWLIST_FILES = new Set([
  "apps/web/src/components/shared/icons.tsx",
  "apps/mobile/src/lib/gaia-icons.tsx",
  "apps/web/src/features/workflows/components/shared/WorkflowCardComponents.tsx",
  "apps/web/src/features/chat/tool-data/cards/streaming-meta-cards.tsx",
  "apps/web/src/app/api/og/shared.tsx",
  "apps/mobile/src/features/chat/tool-data/cards/streaming-meta-cards.tsx",
  "packages/cli/src/ui/screens/init.tsx",
  "packages/cli/src/ui/components/shared-steps.tsx",
  "apps/mobile/src/features/workflows/components/workflow-skeletons.tsx",
  "apps/mobile/src/features/chat/tool-data/primitives/web-result-primitives.tsx",
  "apps/mobile/src/features/settings/components/settings-row.tsx",
]);

const COMPONENT_ALLOWLIST_SUFFIXES = [
  ".stories.tsx",
  ".generated.tsx",
  "icons.tsx",
];

function componentIsAllowed(path) {
  if (COMPONENT_ALLOWLIST_FILES.has(path)) return true;
  if (COMPONENT_ALLOWLIST_PREFIXES.some((p) => path.startsWith(p))) return true;
  if (COMPONENT_ALLOWLIST_SUFFIXES.some((s) => path.endsWith(s))) return true;
  if (path.includes("__tests__/") || path.includes("__mocks__/")) return true;
  if (path.endsWith(".test.tsx") || path.endsWith(".spec.tsx")) return true;
  return false;
}

// This gate only governs .tsx component sources under these roots. The
// explicit-list path mirrors that scope so a diff touching files outside it is
// correctly ignored.
const COMPONENT_SCANNED_ROOTS = [
  "apps/web/src/",
  "apps/desktop/src/",
  "apps/mobile/src/",
  "libs/shared/ts/src/",
  "packages/cli/src/",
];

function componentInScope(path) {
  return (
    path.endsWith(".tsx") &&
    COMPONENT_SCANNED_ROOTS.some((r) => path.startsWith(r))
  );
}

function componentFiles(args) {
  const explicit = explicitFileList(args);
  if (explicit.length > 0) {
    return explicit.filter(componentInScope);
  }
  return gitLsFiles([
    "apps/web/src/**/*.tsx",
    "apps/desktop/src/**/*.tsx",
    "apps/mobile/src/**/*.tsx",
    "libs/shared/ts/src/**/*.tsx",
    "packages/cli/src/**/*.tsx",
  ]);
}

// React component: PascalCase name with at least one lowercase letter (excludes UPPER_SNAKE_CASE constants)
const EXPORT_FN = /^export\s+(default\s+)?function\s+([A-Z][a-z][A-Za-z0-9]*)\s*\(/gm;
const EXPORT_CONST_FN = /^export\s+const\s+([A-Z][a-z][A-Za-z0-9]*)\s*[:=]/gm;

function findComponents(src) {
  const names = new Set();
  for (const m of src.matchAll(EXPORT_FN)) {
    names.add(m[2]);
  }
  for (const m of src.matchAll(EXPORT_CONST_FN)) {
    names.add(m[1]);
  }
  return [...names];
}

const MAX_COMPONENTS_PER_FILE = 2;

function cmdComponentsPerFile(argv) {
  const violations = [];

  for (const file of componentFiles(argv)) {
    if (componentIsAllowed(file)) continue;
    const src = readFileSync(file, "utf8");
    const components = findComponents(src);
    if (components.length > MAX_COMPONENTS_PER_FILE) {
      violations.push({ file, components });
    }
  }

  if (violations.length > 0) {
    violations.sort((a, b) => b.components.length - a.components.length);
    console.error(
      `\n❌ components-per-file gate FAILED — ${violations.length} file(s) export more than ${MAX_COMPONENTS_PER_FILE} React components:\n`,
    );
    for (const v of violations) {
      console.error(`  ${v.file} (${v.components.length} components)`);
      for (const name of v.components) console.error(`    - ${name}`);
    }
    console.error(
      "\nWhy: many components in one file couples unrelated UI, bloats the file," +
        " and makes each component harder to find, test, and reuse.",
    );
    console.error(
      "\nFix: for each file above, move every component past the first" +
        ` ${MAX_COMPONENTS_PER_FILE} into its own file named after the component, and update` +
        " imports. If a sub-component is only used locally, keep it in-file but stop" +
        " exporting it (only exported PascalCase functions/consts are counted here).",
    );
    console.error(
      '\nRule: .claude/rules/general.md § "File Size & Single Responsibility" and' +
        ' apps/web/CLAUDE.md § "React Components". A genuine exception goes in the' +
        " COMPONENT_ALLOWLIST_* lists in scripts/ci/checks.mjs, not around the gate.",
    );
    process.exit(1);
  }

  console.log("✅ All component files within limit.");
}

// ---------------------------------------------------------------------------
// types-location
// ---------------------------------------------------------------------------

function isTypeFile(path) {
  if (path.endsWith(".d.ts")) return true;
  if (path.endsWith(".types.ts") || path.endsWith(".types.tsx")) return true;
  if (path.includes("/types/")) return true;
  if (path.endsWith("/types.ts") || path.endsWith("/types.tsx")) return true;
  // API client files are naturally a contract surface — types and methods are co-located.
  if (path.endsWith("Api.ts") || path.endsWith("-api.ts") || path.endsWith("apiClient.ts")) return true;
  // Schema files (zod / form schemas) declare a discriminated set of types per shape.
  if (path.endsWith("Schemas.ts") || path.endsWith("Schema.ts")) return true;
  // Trigger / event protocol files declare the union of event shapes.
  if (path.endsWith("/triggers.ts")) return true;
  return false;
}

const TYPES_ALLOWLIST_PREFIXES = [
  "apps/web/src/components/ui/",
  "apps/web/src/config/openui/components/",
  "apps/web/src/config/registries/",
  "apps/web/content/",
  "apps/mobile/scripts/",
  "scripts/",
];

function typesIsAllowed(path) {
  if (TYPES_ALLOWLIST_PREFIXES.some((p) => path.startsWith(p))) return true;
  if (path.includes("__tests__/") || path.includes("__mocks__/")) return true;
  if (path.endsWith(".test.ts") || path.endsWith(".test.tsx")) return true;
  if (path.endsWith(".spec.ts") || path.endsWith(".spec.tsx")) return true;
  if (path.endsWith(".stories.tsx")) return true;
  if (path.endsWith(".config.ts") || path.endsWith(".config.tsx")) return true;
  if (path.endsWith(".generated.ts") || path.endsWith(".generated.tsx")) return true;
  // Store / state-management files: state interface + actions interface + selectors are a unit.
  if (path.endsWith("Store.ts") || path.endsWith("Store.tsx")) return true;
  if (path.endsWith("store.ts") || path.endsWith("store.tsx")) return true;
  // Streaming protocol files declare a discriminated-union of event types.
  if (path.endsWith("/streaming.ts")) return true;
  return false;
}

// This gate only governs source under apps/, libs/, packages/ with a .ts/.tsx
// extension. The explicit-list path mirrors that scope so a diff that touches
// unrelated files (e.g. root config) is correctly ignored.
function typesInScope(path) {
  const underTrackedRoot =
    path.startsWith("apps/") ||
    path.startsWith("libs/") ||
    path.startsWith("packages/");
  return underTrackedRoot && (path.endsWith(".ts") || path.endsWith(".tsx"));
}

function typesFiles(args) {
  const explicit = explicitFileList(args);
  if (explicit.length > 0) {
    return explicit.filter(typesInScope);
  }
  return gitLsFiles([
    "apps/**/*.ts",
    "apps/**/*.tsx",
    "libs/**/*.ts",
    "libs/**/*.tsx",
    "packages/**/*.ts",
    "packages/**/*.tsx",
  ]);
}

// Match: `export type X` / `export interface X` / `export enum X`
const TYPE_EXPORT = /^export\s+(type|interface|enum)\s+([A-Za-z0-9_]+)/gm;

// Allow up to 3 type exports per non-types file. This permits natural co-location of
// `Props + 1-2 small helper interfaces`, while still catching files that have grown
// into de-facto type modules (4+ exported types).
const MAX_TYPES_OUTSIDE = 3;

function cmdTypesLocation(argv) {
  const violations = [];

  for (const file of typesFiles(argv)) {
    if (isTypeFile(file)) continue;
    if (typesIsAllowed(file)) continue;

    const src = readFileSync(file, "utf8");
    const matches = [...src.matchAll(TYPE_EXPORT)];
    if (matches.length > MAX_TYPES_OUTSIDE) {
      violations.push({
        file,
        count: matches.length,
        names: matches.map((m) => `${m[1]} ${m[2]}`),
      });
    }
  }

  const args = new Set(argv);
  const enforce = args.has("--enforce") || args.has("--strict");

  if (violations.length > 0) {
    violations.sort((a, b) => b.count - a.count);
    const label = enforce ? "❌" : "ℹ️";
    console.log(
      `\n${label} types-location: ${violations.length} file(s) export more than ${MAX_TYPES_OUTSIDE} types outside a dedicated type file:\n`,
    );
    for (const v of violations) {
      console.log(`  ${v.file} (${v.count} exported types)`);
      for (const name of v.names.slice(0, 3)) console.log(`    - ${name}`);
      if (v.names.length > 3) console.log(`    + ${v.names.length - 3} more`);
    }
    console.log(
      "\nWhy: types scattered across feature files get re-declared instead of reused," +
        " so the same shape drifts into three slightly different versions.",
    );
    console.log(
      "\nFix: for each file above, move its exported type/interface/enum declarations" +
        " into a colocated `*.types.ts` (or a `types.ts` / `types/` directory in the" +
        " same feature) and import them back. A file may keep up to" +
        ` ${MAX_TYPES_OUTSIDE} exported types for local Props/small helpers.`,
    );
    console.log(
      '\nRule: apps/web/CLAUDE.md § "Types" and root CLAUDE.md § Code Style →' +
        " TypeScript (search `src/types/` before creating a new type).",
    );
    if (enforce) {
      process.exit(1);
    } else {
      console.log("(informational only; pass --enforce to fail CI on these)\n");
    }
  } else {
    console.log("✅ Types live in dedicated type files.");
  }
}

// ---------------------------------------------------------------------------
// duplication
//
// Copy-paste gate that matches what SonarCloud actually measures.
//
// jscpd's own threshold is a percentage over the WHOLE repo, so it is ~0.8% and
// never trips for a single PR — a green run there tells you nothing about the
// SonarCloud duplication gate. SonarCloud instead gates on duplicated lines
// among the lines a PR CHANGES (the diff vs the base branch).
//
// This reproduces that denominator: it runs jscpd, then maps every detected
// clone's line ranges onto the lines this branch adds vs the base, and fails
// when that ratio exceeds the limit.
//
// It is an estimate (jscpd's tokenizer differs from SonarCloud's), but it is the
// only local/CI signal correlated with the gate. SonarCloud stays authoritative.
//
// Base branch is GAIA_PR_BASE (resolved from the API by `changes.sh base`),
// falling back to GITHUB_BASE_REF and then to master — the repo's only trunk.
// The order matters: on a stacked PR the event payload names the stack's trunk
// rather than the PR's parent, which would charge this PR with every duplicate
// line the PRs below it added. See the note at the top of changes.sh.
// ---------------------------------------------------------------------------

const DUPLICATION_THRESHOLD = 3;

function cmdDuplication() {
  const baseRef = process.env.GAIA_PR_BASE || process.env.GITHUB_BASE_REF;
  const BASE = baseRef ? `origin/${baseRef}` : "origin/master";

  const sh = (cmd) =>
    execSync(cmd, { encoding: "utf8", maxBuffer: 64 * 1024 * 1024 });

  const repoRoot = sh("git rev-parse --show-toplevel").trim();
  const rel = (p) =>
    p.startsWith(`${repoRoot}/`) ? p.slice(repoRoot.length + 1) : p;

  let base;
  try {
    base = sh(`git merge-base ${BASE} HEAD`).trim();
  } catch {
    // Shallow clone or no common ancestor: fall back to the base ref tip.
    try {
      base = sh(`git rev-parse --verify ${BASE}^{commit}`).trim();
    } catch {
      console.error(
        `checks duplication: could not resolve base "${BASE}". ` +
          "Fetch it first (git fetch origin <branch>).",
      );
      process.exit(2);
    }
  }

  // Lines added on the new side, per file (working tree vs base, so uncommitted
  // changes count too — this is meant to run before you push).
  const added = new Map();
  let currentFile = null;
  for (const line of sh(`git diff --unified=0 ${base}`).split("\n")) {
    if (line.startsWith("+++ ")) {
      const p = line.slice(4).trim();
      currentFile = p === "/dev/null" ? null : p.replace(/^b\//, "");
    } else if (line.startsWith("@@") && currentFile) {
      const m = /\+(\d+)(?:,(\d+))?/.exec(line);
      if (m) {
        const start = Number(m[1]);
        const count = m[2] === undefined ? 1 : Number(m[2]);
        let set = added.get(currentFile);
        if (!set) added.set(currentFile, (set = new Set()));
        for (let i = 0; i < count; i++) set.add(start + i);
      }
    }
  }

  // Run jscpd (reuses config/.jscpd.json) and load the JSON report.
  const outDir = mkdtempSync(join(tmpdir(), "jscpd-"));
  sh(
    `pnpm exec jscpd -c config/.jscpd.json --reporters json --output ${outDir} --silent .`,
  );
  const report = JSON.parse(
    readFileSync(join(outDir, "jscpd-report.json"), "utf8"),
  );

  // Files jscpd analyzed — defines the denominator scope, like SonarCloud.
  const analyzed = new Set();
  for (const fmt of Object.values(report.statistics?.formats ?? {})) {
    for (const f of Object.keys(fmt.sources ?? {})) analyzed.add(rel(f));
  }

  // Lines covered by at least one clone, per file.
  const covered = new Map();
  const cover = (f, s, e) => {
    let set = covered.get(f);
    if (!set) covered.set(f, (set = new Set()));
    for (let i = s; i <= e; i++) set.add(i);
  };
  for (const d of report.duplicates ?? []) {
    cover(rel(d.firstFile.name), d.firstFile.start, d.firstFile.end);
    cover(rel(d.secondFile.name), d.secondFile.start, d.secondFile.end);
  }

  // Changed lines that fall inside a duplicated block, in analyzed files only.
  let changedLines = 0;
  let dupChangedLines = 0;
  const offenders = [];
  for (const [file, addedSet] of added) {
    if (!analyzed.has(file)) continue;
    changedLines += addedSet.size;
    const cov = covered.get(file);
    if (!cov) continue;
    let n = 0;
    for (const ln of addedSet) if (cov.has(ln)) n++;
    if (n > 0) {
      dupChangedLines += n;
      offenders.push([file, n]);
    }
  }

  const density =
    changedLines === 0 ? 0 : (dupChangedLines / changedLines) * 100;
  console.log(
    `Duplication on changed lines (estimate vs ${BASE}): ${density.toFixed(2)}%  ` +
      `(${dupChangedLines}/${changedLines} changed lines in duplicated blocks)`,
  );
  if (offenders.length) {
    console.log("Files contributing duplicated changed lines:");
    for (const [f, n] of offenders.sort((a, b) => b[1] - a[1])) {
      console.log(`  ${String(n).padStart(4)}  ${f}`);
    }
  }
  console.log(`Limit: <= ${DUPLICATION_THRESHOLD}% (SonarCloud is authoritative).`);

  if (density > DUPLICATION_THRESHOLD) {
    console.error(
      `\n❌ duplicates gate FAILED — ${density.toFixed(2)}% of your changed lines` +
        ` sit inside copy-pasted blocks (limit ${DUPLICATION_THRESHOLD}%).`,
    );
    console.error(
      "\nWhy: copy-pasted logic drifts — one copy gets fixed, the other rots into a" +
        " bug — and forces every reader to learn which variant to trust.",
    );
    console.error(
      "\nFix: for each file under 'Files contributing duplicated changed lines'" +
        " above, extract the duplicated block into a single shared function and call" +
        " it from both sites — put cross-app helpers in libs/shared/ts/src (imported" +
        " as @gaia/shared), feature-local ones in that feature's utils. Do not paste" +
        " the block a third time.",
    );
    console.error(
      '\nRule: .claude/rules/general.md § "DRY — Search Before You Build" and root' +
        " CLAUDE.md (never write the same code twice). SonarCloud stays authoritative.",
    );
    process.exit(1);
  }
}


// ---------------------------------------------------------------------------
// api-schema
//
// The contract between the API and every TypeScript consumer is the committed
// openapi.json plus the types generated from it. Both are build outputs, so
// the only honest check is to rebuild them and diff: a route change that was
// committed without `mise api:types` shows up here as a dirty tree.
// ---------------------------------------------------------------------------

const OPENAPI_JSON = "apps/api/openapi.json";
const GENERATED_TYPES = "libs/shared/ts/src/api/generated/schema.d.ts";
const API_SCHEMA_DRIFT_MESSAGE =
  "API schema drifted — run `mise api:types` and commit";

function regenerateApiSchema() {
  const opts = { stdio: "inherit" };
  execFileSync(
    "uv",
    [
      "run",
      "--frozen",
      "--project",
      "apps/api",
      "--group",
      "backend",
      "--group",
      "dev",
      "python",
      "apps/api/scripts/export_openapi.py",
    ],
    { ...opts, env: { ...process.env, LOG_LEVEL: "ERROR" } },
  );
  execFileSync(
    "pnpm",
    [
      "exec",
      "openapi-typescript",
      OPENAPI_JSON,
      "--alphabetize",
      // A field with a default is optional on the wire for a request body; a
      // response-only model marks it required itself (ResponseModel).
      "--default-non-nullable=false",
      // One exported alias per component schema, under the API's own name
      // (`TodoResponse`, not `Schema<"TodoResponse">`): navigable, greppable,
      // and identical to the Pydantic class it came from.
      "--root-types",
      "--root-types-no-schema-prefix",
      "--root-types-keep-casing",
      "--output",
      GENERATED_TYPES,
    ],
    opts,
  );
}

function cmdApiSchema(argv) {
  regenerateApiSchema();
  if (argv.includes("--write")) return;

  const dirty = execFileSync(
    "git",
    ["status", "--porcelain", "--", OPENAPI_JSON, GENERATED_TYPES],
    { encoding: "utf8" },
  ).trim();
  if (dirty) {
    console.log(dirty);
    console.error(`❌ ${API_SCHEMA_DRIFT_MESSAGE}`);
    process.exit(1);
  }
  console.log("✅ openapi.json and the generated API types match the routes.");
}

// ---------------------------------------------------------------------------
// api-schema-types
// ---------------------------------------------------------------------------

const GENERATED_DIR = "libs/shared/ts/src/api/generated/";
// `export interface TodoResponse {`, `type Workflow<T> =`, `declare interface X extends`.
// The trailing `{ < = extends` is what separates a declaration from the
// `type Foo,` line of a multi-line `import type` list.
const TYPE_DECLARATION =
  /^\s*(?:export\s+)?(?:declare\s+)?(?:interface|type)\s+([A-Za-z0-9_]+)\s*(?:<|\{|=|extends\b)/gm;
// `export type Workflow = WorkflowWithIntegrations;` names a generated type
// for a feature's consumers — zero fields of its own, so it cannot drift.
// Anything else with the name is a twin. The right-hand side is a schema
// name, or a local name bound to one by `import type { X as Y }` (the form a
// type-plus-`const` pair like `Priority` needs).
const GENERATED_IMPORT = /^import type \{([^}]*)\} from "[^"]*generated";/gm;
function generatedBindings(src, names) {
  const bound = new Set();
  for (const [, list] of src.matchAll(GENERATED_IMPORT)) {
    for (const entry of list.split(",")) {
      const [imported, local = imported] = entry.trim().split(/\s+as\s+/);
      if (names.has(imported)) bound.add(local);
    }
  }
  return bound;
}
const schemaAliasIn = (src, name, names) => {
  const alias = src.match(
    new RegExp(`^\\s*(?:export\\s+)?type\\s+${name}\\s*=\\s*([A-Za-z0-9_]+);`, "m"),
  );
  return alias !== null && (names.has(alias[1]) || generatedBindings(src, names).has(alias[1]));
};

function schemaComponentNames() {
  const doc = JSON.parse(readFileSync(OPENAPI_JSON, "utf8"));
  return new Set(Object.keys(doc.components?.schemas ?? {}));
}

function schemaTwinsIn(file, names) {
  const src = readFileSync(file, "utf8");
  return [...src.matchAll(TYPE_DECLARATION)]
    .map((m) => m[1])
    .filter((name) => names.has(name) && !schemaAliasIn(src, name, names));
}

// The web's API layer. `apiService` is the untyped request engine behind the
// path-typed client (`lib/api/typed.ts`); only this directory may touch it.
const WEB_API_LIB = "apps/web/src/lib/api/";
const WEB_SRC = "apps/web/src/";
const UNTYPED_CALL = /\bapiService\b/;

function untypedCallLines(file) {
  const lines = readFileSync(file, "utf8").split("\n");
  return lines
    .map((line, index) => (UNTYPED_CALL.test(line) ? index + 1 : 0))
    .filter(Boolean);
}

function isWebFeatureFile(file) {
  return (
    file.startsWith(WEB_SRC) &&
    !file.startsWith(WEB_API_LIB) &&
    !file.includes("/__tests__/") &&
    !/\.test\.tsx?$/.test(file)
  );
}

function cmdApiSchemaTypes(argv) {
  const names = schemaComponentNames();
  // existsSync: `git ls-files` still lists a file deleted but not yet staged.
  const scanned = typesFiles(argv).filter(
    (file) =>
      !file.startsWith(GENERATED_DIR) && !shouldIgnore(file) && existsSync(file),
  );

  const violations = [];
  const untyped = [];
  for (const file of scanned) {
    const found = schemaTwinsIn(file, names);
    if (found.length > 0) violations.push({ file, names: found });
    if (isWebFeatureFile(file)) {
      const lines = untypedCallLines(file);
      if (lines.length > 0) untyped.push({ file, lines });
    }
  }

  if (violations.length > 0) {
    console.log(
      `\n❌ api-schema-types: ${violations.length} file(s) hand-write a type that mirrors an API model:\n`,
    );
    for (const v of violations) {
      for (const name of v.names) {
        console.log(
          `  ${v.file}: ${name} — import type { ${name} } from "@gaia/shared/api/generated"`,
        );
      }
    }
    console.log(
      "\nWhy: a hand-written twin of a Pydantic model drifts the moment the model changes;" +
        " the generated type is regenerated by `mise api:types` and cannot.",
    );
  }
  if (untyped.length > 0) {
    console.log(
      `\n❌ api-schema-types: ${untyped.length} file(s) call the untyped apiService outside apps/web/src/lib/api:\n`,
    );
    for (const u of untyped) {
      console.log(
        `  ${u.file}:${u.lines.join(",")} — use \`api\` from "@/lib/api/typed" (the path-typed client)`,
      );
    }
    console.log(
      "\nWhy: apiService takes any URL and any type argument, so a typo in the path or a" +
        " guessed response shape compiles; the typed client checks both against openapi.json.",
    );
  }
  if (violations.length > 0 || untyped.length > 0) process.exit(1);
  console.log(
    "✅ No hand-written twins of API schema types; every web API call is path-typed.",
  );
}

// ---------------------------------------------------------------------------
// dispatch
// ---------------------------------------------------------------------------

function usage() {
  console.error(
    [
      "usage: node scripts/ci/checks.mjs <subcommand> [args]",
      "",
      "  file-sizes [--enforce-all] [--quiet]   per-file line limits + 1200 hard cap",
      "  components-per-file                    max 2 exported React components per .tsx",
      "  types-location [--enforce]             max 3 exported types outside a type file",
      "  duplication                            copy-paste density on changed lines",
      "  evlog-map-bots [--json] [--min-score N] [--min-entries N] [--files-from F]",
      "                                         observability score for bot entry points",
      "  api-schema [--write]                   regenerate openapi.json + TS types, fail on drift",
      "  api-schema-types                       no hand-written twin of an API schema type, no untyped apiService call in web features",
    ].join("\n"),
  );
}

function main() {
  const sub = process.argv[2];
  const rest = process.argv.slice(3);
  switch (sub) {
    case "file-sizes":
      cmdFileSizes(rest);
      break;
    case "components-per-file":
      cmdComponentsPerFile(rest);
      break;
    case "types-location":
      cmdTypesLocation(rest);
      break;
    case "duplication":
      cmdDuplication(rest);
      break;
    case "evlog-map-bots":
      runEvlogMapBots(rest);
      break;
    case "api-schema":
      cmdApiSchema(rest);
      break;
    case "api-schema-types":
      cmdApiSchemaTypes(rest);
      break;
    default:
      console.error(`checks.mjs: unknown subcommand '${sub ?? ""}'`);
      usage();
      process.exit(2);
  }
}

main();
