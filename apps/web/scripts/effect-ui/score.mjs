#!/usr/bin/env node
/**
 * Hillclimb score for the Effect UI migration.
 *
 * The primary metric is the fraction of Next.js pages routed through the Effect
 * UI. A page counts as ported only when its `page.tsx` carries an
 * `effect === "1"` branch AND imports an Effect UI component, so a dead branch
 * cannot raise the score.
 *
 * The gate is zero React, HeroUI, Radix, or Next imports under
 * `packages/effect-ui/src`, which keeps the package renderer-agnostic. A gate
 * failure zeroes the score: route count is never traded for the wrong runtime.
 *
 * Usage: node apps/web/scripts/effect-ui/score.mjs [--json]
 * Exit 1 on a forbidden import or a missing input tree.
 */
import { existsSync, readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../../..",
);

const APP_DIR = path.join(ROOT, "apps/web/src/app");
const EFFECT_COMPONENTS_DIR = path.join(ROOT, "apps/web/src/components/effect");
const EFFECT_UI_SRC = path.join(ROOT, "packages/effect-ui/src");
const EFFECT_UI_PAGES = path.join(EFFECT_UI_SRC, "pages");
const EFFECT_UI_TESTS = path.join(ROOT, "packages/effect-ui/test");
const E2E_DIR = path.join(ROOT, "apps/web/e2e/effect-ui");

const CODE_EXTENSIONS = new Set([".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs"]);

const FORBIDDEN = [
  {
    rule: "react",
    matches: (spec) =>
      spec === "react" ||
      spec === "react-dom" ||
      spec.startsWith("react/") ||
      spec.startsWith("react-dom/"),
  },
  {
    rule: "@heroui",
    matches: (spec) => spec === "@heroui" || spec.startsWith("@heroui/"),
  },
  {
    rule: "@radix-ui",
    matches: (spec) => spec === "@radix-ui" || spec.startsWith("@radix-ui/"),
  },
  {
    rule: "next",
    matches: (spec) => spec === "next" || spec.startsWith("next/"),
  },
];

const IMPORT_PATTERNS = [
  /\b(?:import|export)\s+(?:type\s+)?[^"'`]*?\bfrom\s*["']([^"']+)["']/g,
  /\bimport\s*["']([^"']+)["']/g,
  /\bimport\s*\(\s*["']([^"']+)["']\s*\)/g,
  /\brequire\s*\(\s*["']([^"']+)["']\s*\)/g,
];

function walk(dir) {
  if (!existsSync(dir)) return [];
  const files = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    if (entry.name === "node_modules" || entry.name === ".next") continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) files.push(...walk(full));
    else if (entry.isFile()) files.push(full);
  }
  return files;
}

const byPath = (a, b) => a.localeCompare(b);

function routeOf(pageFile) {
  const rel = path.relative(APP_DIR, path.dirname(pageFile)).split(path.sep).join("/");
  return rel === "" ? "/" : `/${rel}`;
}

function lineOf(text, index) {
  let line = 1;
  for (let i = 0; i < index; i += 1) {
    if (text.charCodeAt(i) === 10) line += 1;
  }
  return line;
}

function importsIn(text) {
  const specs = [];
  for (const pattern of IMPORT_PATTERNS) {
    for (const match of text.matchAll(pattern)) {
      specs.push({ spec: match[1], index: match.index ?? 0 });
    }
  }
  return specs;
}

function scanReactImports() {
  const violations = [];
  const files = walk(EFFECT_UI_SRC)
    .filter((file) => CODE_EXTENSIONS.has(path.extname(file)))
    .sort(byPath);

  for (const file of files) {
    const text = readFileSync(file, "utf8");
    for (const { spec, index } of importsIn(text)) {
      const rule = FORBIDDEN.find((candidate) => candidate.matches(spec));
      if (!rule) continue;
      violations.push({
        file: path.relative(ROOT, file).split(path.sep).join("/"),
        line: lineOf(text, index),
        spec,
        rule: rule.rule,
      });
    }
  }

  return {
    count: violations.length,
    filesScanned: files.length,
    violations: violations.sort(
      (a, b) => byPath(a.file, b.file) || a.line - b.line,
    ),
  };
}

const missing = [APP_DIR, EFFECT_UI_SRC].filter((dir) => !existsSync(dir));
if (missing.length > 0) {
  console.error(
    `missing input tree: ${missing.map((dir) => path.relative(ROOT, dir)).join(", ")}`,
  );
  console.error(`repo root resolved to ${ROOT}`);
  process.exit(1);
}

const pageFiles = walk(APP_DIR)
  .filter((file) => path.basename(file) === "page.tsx")
  .sort(byPath);

const routes = pageFiles.map((file) => {
  const source = readFileSync(file, "utf8");
  const branch = /\beffect\s*===\s*["']1["']/.test(source);
  const linked =
    source.includes("@/components/effect/") ||
    source.includes("@heygaia/effect-ui");
  return {
    route: routeOf(file),
    file: path.relative(ROOT, file).split(path.sep).join("/"),
    branch,
    linked: branch && linked,
  };
});

const adapterFiles = walk(path.join(EFFECT_COMPONENTS_DIR, "pages"))
  .filter((file) => path.extname(file) === ".tsx")
  .sort(byPath);

const branchImports = walk(EFFECT_COMPONENTS_DIR)
  .filter(
    (file) =>
      path.basename(file).startsWith("Effect") &&
      path.basename(file).endsWith("Branch.tsx"),
  )
  .map((file) => readFileSync(file, "utf8"))
  .join("\n");

const adapterImports = [
  ...pageFiles.map((file) => readFileSync(file, "utf8")),
  branchImports,
].join("\n");

const adapters = adapterFiles.map((file) => {
  const name = path.basename(file, ".tsx");
  const rel = path.relative(ROOT, file).split(path.sep).join("/");
  return {
    name,
    file: rel,
    importedByPage: new RegExp(`/pages/${name}(?![\\w])`).test(adapterImports),
  };
});

const effectPageModules = walk(EFFECT_UI_PAGES)
  .filter((file) => path.extname(file) === ".ts")
  .sort(byPath);
const effectTests = walk(EFFECT_UI_TESTS)
  .filter((file) => file.endsWith(".test.ts"))
  .sort(byPath);
const e2eSpecs = walk(E2E_DIR)
  .filter((file) => file.endsWith(".spec.ts"))
  .sort(byPath);

const reactImports = scanReactImports();

const portedRoutes = routes.filter((route) => route.linked);
const remainingRoutes = routes.filter((route) => !route.linked);
const branchRoutes = routes.filter((route) => route.branch);

const total = routes.length;
const ported = portedRoutes.length;
const ratio = total === 0 ? 0 : ported / total;
const gatePass = reactImports.count === 0;
const score = gatePass ? ratio : 0;

const report = {
  score: Number(score.toFixed(4)),
  gate: {
    zeroReactImports: gatePass,
  },
  routes: {
    total,
    ported,
    remaining: remainingRoutes.length,
    pct: Number((ratio * 100).toFixed(2)),
    branches: branchRoutes.length,
    portedList: portedRoutes.map((route) => route.route),
    remainingList: remainingRoutes.map((route) => route.route),
    unlinkedBranches: branchRoutes
      .filter((route) => !route.linked)
      .map((route) => route.route),
  },
  adapters: {
    count: adapters.length,
    files: adapters.map((adapter) => adapter.file),
    orphans: adapters
      .filter((adapter) => !adapter.importedByPage)
      .map((adapter) => adapter.file),
  },
  effectUi: {
    pageModules: effectPageModules.length,
    testFiles: effectTests.length,
    e2eSpecs: e2eSpecs.length,
    testsPerPortedPage: Number(
      (effectTests.length / Math.max(ported, 1)).toFixed(2),
    ),
    e2ePerPortedPage: Number(
      (e2eSpecs.length / Math.max(ported, 1)).toFixed(2),
    ),
  },
  reactImports,
  target: {
    portedPages: total,
    zeroReactImports: true,
  },
  met: {
    portedPages: ported === total,
    zeroReactImports: gatePass,
  },
};

if (process.argv.includes("--json")) {
  console.log(JSON.stringify(report, null, 2));
} else {
  const rows = [
    ["Next pages", String(report.routes.total), String(report.target.portedPages)],
    ["Ported routes", String(report.routes.ported), String(report.target.portedPages)],
    ['  effect === "1" branches', String(report.routes.branches), ""],
    ["  unlinked branches", String(report.routes.unlinkedBranches.length), ""],
    ["Effect UI page modules", String(report.effectUi.pageModules), ""],
    ["Effect UI test files", String(report.effectUi.testFiles), ""],
    ["E2E effect-ui specs", String(report.effectUi.e2eSpecs), ""],
    ["React imports in src", String(report.reactImports.count), "0"],
  ];

  const labelWidth = Math.max(...rows.map(([label]) => label.length), "score".length) + 2;
  const pad = (value, width) => String(value).padStart(width);
  const line = (label, value, target) =>
    `${label.padEnd(labelWidth)}${pad(value, 8)}${pad(target, 9)}`;

  console.log("Effect UI migration score");
  console.log("-------------------------");
  console.log(line("metric", "value", "target"));
  for (const [label, value, target] of rows) {
    console.log(line(label, value, target));
  }
  console.log("");
  console.log(
    `score ${report.score.toFixed(4)}  (${ported}/${total} routes, ${report.routes.pct.toFixed(1)}%)`,
  );
  console.log(
    `gate  ${gatePass ? "PASS" : "FAIL"}  zero forbidden imports under packages/effect-ui/src`,
  );

  if (report.adapters.orphans.length > 0) {
    console.warn("\nunreferenced adapters:");
    for (const file of report.adapters.orphans) console.warn(`  ${file}`);
  }
  if (report.routes.unlinkedBranches.length > 0) {
    console.warn("\neffect branches without an Effect UI import:");
    for (const route of report.routes.unlinkedBranches) console.warn(`  ${route}`);
  }
  if (report.reactImports.count > 0) {
    console.error("\nforbidden imports:");
    for (const violation of report.reactImports.violations) {
      console.error(`  ${violation.file}:${violation.line}  ${violation.spec}  (${violation.rule})`);
    }
  }
}

process.exitCode = gatePass ? 0 : 1;
