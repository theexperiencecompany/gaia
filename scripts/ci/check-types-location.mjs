#!/usr/bin/env node
import { readFileSync } from "node:fs";
import { execSync } from "node:child_process";

function isTypeFile(path) {
  if (path.endsWith(".d.ts")) return true;
  if (path.endsWith(".types.ts") || path.endsWith(".types.tsx")) return true;
  if (path.includes("/types/")) return true;
  if (path.endsWith("/types.ts") || path.endsWith("/types.tsx")) return true;
  return false;
}

const ALLOWLIST_PREFIXES = [
  "apps/web/src/components/ui/",
  "apps/web/src/config/openui/components/",
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
  return false;
}

function getFiles() {
  const out = execSync(
    "git ls-files 'apps/**/*.{ts,tsx}' 'libs/**/*.{ts,tsx}' 'packages/**/*.{ts,tsx}'",
    { encoding: "utf8" },
  );
  return out.trim().split("\n").filter(Boolean);
}

// Match: `export type X` / `export interface X` / `export enum X`
const TYPE_EXPORT = /^export\s+(type|interface|enum)\s+([A-Za-z0-9_]+)/gm;

const violations = [];
const MAX_TYPES_OUTSIDE = 1;

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

if (violations.length > 0) {
  violations.sort((a, b) => b.count - a.count);
  console.error(
    `\n❌ ${violations.length} file(s) export more than ${MAX_TYPES_OUTSIDE} type outside a types file:\n`,
  );
  for (const v of violations) {
    console.error(`  ${v.file} (${v.count})`);
    for (const name of v.names.slice(0, 5))
      console.error(`    - ${name}`);
    if (v.names.length > 5) console.error(`    + ${v.names.length - 5} more`);
  }
  console.error(
    "\nMove exported types/interfaces/enums into a *.types.ts, types.ts, or types/ directory.\n",
  );
  process.exit(1);
}

console.log("✅ Types live in dedicated type files.");
