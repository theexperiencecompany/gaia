#!/usr/bin/env node
import { readFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { explicitFileList } from "./lib/explicit-file-list.mjs";

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

const ALLOWLIST_PREFIXES = [
  "apps/web/src/components/ui/",
  "apps/web/src/config/openui/components/",
  "apps/web/src/config/registries/",
  "apps/web/content/",
  "apps/mobile/scripts/",
  "scripts/",
];

function isAllowed(path) {
  if (ALLOWLIST_PREFIXES.some((p) => path.startsWith(p))) return true;
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
function inScope(path) {
  const underTrackedRoot =
    path.startsWith("apps/") ||
    path.startsWith("libs/") ||
    path.startsWith("packages/");
  return underTrackedRoot && (path.endsWith(".ts") || path.endsWith(".tsx"));
}

function getFiles() {
  const explicit = explicitFileList();
  if (explicit.length > 0) {
    return explicit.filter(inScope);
  }
  // `git` is intentionally resolved via PATH on CI runners and local dev
  // shells where the binary is part of the runtime.
  const out = execFileSync( // NOSONAR javascript:S4036
    "git", // NOSONAR javascript:S4036
    [
      "ls-files",
      "apps/**/*.ts",
      "apps/**/*.tsx",
      "libs/**/*.ts",
      "libs/**/*.tsx",
      "packages/**/*.ts",
      "packages/**/*.tsx",
    ],
    { encoding: "utf8" },
  );
  return out.trim().split("\n").filter(Boolean);
}

// Match: `export type X` / `export interface X` / `export enum X`
const TYPE_EXPORT = /^export\s+(type|interface|enum)\s+([A-Za-z0-9_]+)/gm;

const violations = [];
// Allow up to 3 type exports per non-types file. This permits natural co-location of
// `Props + 1-2 small helper interfaces`, while still catching files that have grown
// into de-facto type modules (4+ exported types).
const MAX_TYPES_OUTSIDE = 3;

for (const file of getFiles()) {
  if (isTypeFile(file)) continue;
  if (isAllowed(file)) continue;

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

const args = new Set(process.argv.slice(2));
const enforce = args.has("--enforce") || args.has("--strict");

if (violations.length > 0) {
  violations.sort((a, b) => b.count - a.count);
  const label = enforce ? "❌" : "ℹ️";
  console.log(
    `\n${label} ${violations.length} file(s) export more than ${MAX_TYPES_OUTSIDE} type outside a types file:\n`,
  );
  for (const v of violations) {
    console.log(`  ${v.file} (${v.count})`);
    for (const name of v.names.slice(0, 3)) console.log(`    - ${name}`);
    if (v.names.length > 3) console.log(`    + ${v.names.length - 3} more`);
  }
  console.log(
    "\nMove exported types/interfaces/enums into a *.types.ts, types.ts, or types/ directory.",
  );
  if (enforce) {
    process.exit(1);
  } else {
    console.log("(informational only; pass --enforce to fail CI on these)\n");
  }
} else {
  console.log("✅ Types live in dedicated type files.");
}
