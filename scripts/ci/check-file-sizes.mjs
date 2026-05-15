#!/usr/bin/env node
import { readFileSync } from "node:fs";
import { execSync } from "node:child_process";

const LIMITS = {
  ".tsx": 400,
  ".ts": 500,
  ".jsx": 400,
  ".js": 500,
};

const ALLOWLIST = new Set([
  "apps/web/src/components/shared/icons.tsx",
  "apps/mobile/src/lib/gaia-icons.tsx",
]);

const ALLOWLIST_PREFIXES = [
  "apps/web/src/components/ui/",
  "apps/web/content/",
  "apps/web/src/i18n/",
  "apps/web/src/config/openui/components/",
  "apps/web/src/features/alternatives/data/",
  "apps/web/src/features/comparisons/data/",
  "apps/web/src/features/glossary/data/",
  "apps/web/src/features/personas/data/",
  "apps/web/src/features/integrations/data/",
  "apps/web/src/features/landing/components/demo/",
  "apps/web/src/lib/",
  "apps/web/src/config/iconPaths.generated",
  "apps/mobile/scripts/",
];

const ALLOWLIST_SUFFIXES = [".generated.ts", ".generated.tsx", ".d.ts"];

function isAllowed(path) {
  if (ALLOWLIST.has(path)) return true;
  if (ALLOWLIST_PREFIXES.some((p) => path.startsWith(p))) return true;
  if (ALLOWLIST_SUFFIXES.some((s) => path.endsWith(s))) return true;
  return false;
}

function getFiles() {
  const out = execSync(
    "git ls-files 'apps/**/*.{ts,tsx,js,jsx}' 'libs/**/*.{ts,tsx,js,jsx}' 'packages/**/*.{ts,tsx,js,jsx}'",
    { encoding: "utf8" },
  );
  return out.trim().split("\n").filter(Boolean);
}

function countLines(path) {
  return readFileSync(path, "utf8").split("\n").length;
}

function ext(path) {
  const dot = path.lastIndexOf(".");
  return dot === -1 ? "" : path.slice(dot);
}

const violations = [];
for (const file of getFiles()) {
  if (isAllowed(file)) continue;
  if (file.includes("__tests__/") || file.includes("__mocks__/")) continue;
  if (file.endsWith(".test.ts") || file.endsWith(".test.tsx")) continue;
  if (file.endsWith(".spec.ts") || file.endsWith(".spec.tsx")) continue;
  const limit = LIMITS[ext(file)];
  if (!limit) continue;
  const lines = countLines(file);
  if (lines > limit) {
    violations.push({ file, lines, limit });
  }
}

if (violations.length > 0) {
  violations.sort((a, b) => b.lines - a.lines);
  console.error(`\n❌ ${violations.length} file(s) exceed size limits:\n`);
  for (const v of violations) {
    console.error(`  ${v.file} (${v.lines} lines, limit ${v.limit})`);
  }
  console.error(
    "\nSplit large files into smaller, focused modules. If a file must exceed the limit,",
  );
  console.error(
    "add it to ALLOWLIST or ALLOWLIST_PREFIXES in scripts/ci/check-file-sizes.mjs.\n",
  );
  process.exit(1);
}

console.log("✅ All files within size limits.");
