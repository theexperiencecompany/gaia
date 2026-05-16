#!/usr/bin/env node
import { readFileSync } from "node:fs";
import { execFileSync } from "node:child_process";

const ALLOWLIST_PREFIXES = [
  "apps/web/src/components/ui/",
  "apps/web/src/config/openui/components/",
  "apps/web/src/features/landing/components/demo/",
  "apps/web/content/",
  "apps/web/src/lib/",
  "apps/mobile/src/config/openui/components/",
];

const ALLOWLIST_FILES = new Set([
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

const ALLOWLIST_SUFFIXES = [".stories.tsx", ".generated.tsx", "icons.tsx"];

function isAllowed(path) {
  if (ALLOWLIST_FILES.has(path)) return true;
  if (ALLOWLIST_PREFIXES.some((p) => path.startsWith(p))) return true;
  if (ALLOWLIST_SUFFIXES.some((s) => path.endsWith(s))) return true;
  if (path.includes("__tests__/") || path.includes("__mocks__/")) return true;
  if (path.endsWith(".test.tsx") || path.endsWith(".spec.tsx")) return true;
  return false;
}

function getFiles() {
  // `git` is intentionally resolved via PATH; CI runners always have it.
  const out = execFileSync( // NOSONAR javascript:S4036
    "git", // NOSONAR javascript:S4036
    [
      "ls-files",
      "apps/web/src/**/*.tsx",
      "apps/desktop/src/**/*.tsx",
      "apps/mobile/src/**/*.tsx",
      "libs/shared/ts/src/**/*.tsx",
      "packages/cli/src/**/*.tsx",
    ],
    { encoding: "utf8" },
  );
  return out.trim().split("\n").filter(Boolean);
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

const violations = [];
const MAX_PER_FILE = 2;

for (const file of getFiles()) {
  if (isAllowed(file)) continue;
  const src = readFileSync(file, "utf8");
  const components = findComponents(src);
  if (components.length > MAX_PER_FILE) {
    violations.push({ file, components });
  }
}

if (violations.length > 0) {
  violations.sort((a, b) => b.components.length - a.components.length);
  console.error(
    `\n❌ ${violations.length} file(s) export more than ${MAX_PER_FILE} components:\n`,
  );
  for (const v of violations) {
    console.error(`  ${v.file} (${v.components.length})`);
    for (const name of v.components) console.error(`    - ${name}`);
  }
  console.error(
    `\nSplit each component into its own file. If a sub-component is private,`,
  );
  console.error("don't export it. Allowlist in scripts/ci/check-components-per-file.mjs.\n");
  process.exit(1);
}

console.log("✅ All component files within limit.");
