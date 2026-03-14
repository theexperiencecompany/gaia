#!/usr/bin/env node
/**
 * barrel-to-direct.mjs
 *
 * Rewrites barrel-export imports to direct file imports across the GAIA monorepo.
 * Fixes Turbopack/HMR slowness caused by large barrel re-export chains.
 *
 * Usage:
 *   node scripts/barrel-to-direct.mjs [--dry-run] [--app=web|mobile|shared|desktop|all]
 *
 * What it does:
 *   1. Walks TS/TSX files in the target app src directory
 *   2. Identifies barrel files (index.ts/tsx that only contain re-exports)
 *   3. Builds an export registry: symbol → true source file (recursively resolves export* chains)
 *   4. Rewrites consumer import statements to point directly at source files
 *
 * Excluded: anything under an /icons/ path segment (icon barrels are intentional)
 */

import { readFileSync, writeFileSync, readdirSync, statSync } from "fs";
import { resolve, dirname, join, relative, basename } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, "..");
const DRY_RUN = process.argv.includes("--dry-run");
const APP_ARG =
  process.argv.find((a) => a.startsWith("--app="))?.split("=")[1] ?? "all";

// ─── App configurations ───────────────────────────────────────────────────────

const APP_CONFIGS = {
  web: {
    srcDir: join(ROOT, "apps/web/src"),
    alias: {
      "@/": join(ROOT, "apps/web/src") + "/",
      "@shared/": join(ROOT, "libs/shared/ts/src") + "/",
    },
  },
  mobile: {
    srcDir: join(ROOT, "apps/mobile/src"),
    alias: {
      "@/": join(ROOT, "apps/mobile/src") + "/",
      "@shared/": join(ROOT, "libs/shared/ts/src") + "/",
    },
  },
  desktop: {
    srcDir: join(ROOT, "apps/desktop/src"),
    alias: {
      "@/": join(ROOT, "apps/desktop/src") + "/",
      "@shared/": join(ROOT, "libs/shared/ts/src") + "/",
    },
  },
  shared: {
    srcDir: join(ROOT, "libs/shared/ts/src"),
    alias: {},
  },
};

const APPS_TO_PROCESS =
  APP_ARG === "all" ? Object.keys(APP_CONFIGS) : [APP_ARG];

// ─── Utilities ────────────────────────────────────────────────────────────────

function isIconPath(absPath) {
  // Skip any path that has /icons/ or /icon/ as a directory segment
  return /[/\\]icons[/\\]/.test(absPath) || /[/\\]icons$/.test(absPath);
}

function safeRead(p) {
  try {
    return readFileSync(p, "utf8");
  } catch {
    return "";
  }
}

const SKIP_DIRS = new Set([
  "node_modules",
  ".next",
  ".expo",
  "dist",
  "__generated__",
  ".turbo",
  ".cache",
  "coverage",
]);

function walkTs(dir, files = []) {
  let entries;
  try {
    entries = readdirSync(dir, { withFileTypes: true });
  } catch {
    return files;
  }
  for (const entry of entries) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      if (SKIP_DIRS.has(entry.name)) continue;
      walkTs(full, files);
    } else if (/\.(ts|tsx)$/.test(entry.name)) {
      files.push(full);
    }
  }
  return files;
}

// ─── Barrel detection ─────────────────────────────────────────────────────────

function isBarrelFile(filePath, content) {
  const name = basename(filePath);
  if (name !== "index.ts" && name !== "index.tsx") return false;
  if (isIconPath(filePath)) return false;
  if (!content.includes(" from ")) return false;

  const lines = content.split("\n");
  const meaningful = lines
    .map((l) => l.trim())
    .filter(
      (l) =>
        l &&
        !l.startsWith("//") &&
        !l.startsWith("*") &&
        !l.startsWith("/*") &&
        !l.startsWith("/**") &&
        l !== "{"  &&
        l !== "}"
    );

  if (meaningful.length === 0) return false;

  const reExportLines = meaningful.filter(
    (l) =>
      /^export\s*\*\s+from\s+['"]/.test(l) ||
      /^export\s*\{[^}]*\}\s+from\s+['"]/.test(l)
  );

  // Lines that are NOT re-exports and NOT JSDoc/comments/imports
  const implLines = meaningful.filter(
    (l) =>
      !/^export/.test(l) &&
      !/^import\s/.test(l) &&
      !/^\/\*/.test(l) &&
      !/^\*/.test(l) &&
      !/^["']use/.test(l) // 'use client' etc
  );

  return reExportLines.length > 0 && implLines.length === 0;
}

// ─── Import resolution ────────────────────────────────────────────────────────

function resolveImport(specifier, fromFile, aliases) {
  if (specifier.startsWith(".")) {
    const base = resolve(dirname(fromFile), specifier);
    // Try file extensions first (skip empty "" to avoid matching directories)
    for (const ext of [".ts", ".tsx", "/index.ts", "/index.tsx"]) {
      try {
        const candidate = base + ext;
        const s = statSync(candidate);
        if (s.isFile()) return candidate;
      } catch {}
    }
    return null;
  }

  // Try path aliases (longest prefix first for correctness)
  const sortedAliases = Object.entries(aliases).sort(
    ([a], [b]) => b.length - a.length
  );
  for (const [prefix, absPrefix] of sortedAliases) {
    if (specifier.startsWith(prefix)) {
      const rest = specifier.slice(prefix.length);
      const base = join(absPrefix, rest);
      // Try file extensions first (skip empty "" to avoid matching directories)
      for (const ext of [".ts", ".tsx", "/index.ts", "/index.tsx"]) {
        try {
          const candidate = base + ext;
          const s = statSync(candidate);
          if (s.isFile()) return candidate;
        } catch {}
      }
      return null;
    }
  }

  return null; // external package — skip
}

// ─── Export registry ──────────────────────────────────────────────────────────

// Cache: absPath → Map<exportedSymbol, sourceAbsPath>
const barrelCache = new Map();

function getBarrelExports(barrelPath, aliases, visited = new Set()) {
  if (barrelCache.has(barrelPath)) return barrelCache.get(barrelPath);
  if (visited.has(barrelPath)) return new Map();

  const newVisited = new Set(visited);
  newVisited.add(barrelPath);

  const result = new Map(); // symbol → true source file
  const content = safeRead(barrelPath);

  for (const rawLine of content.split("\n")) {
    const line = rawLine.trim();

    // export * from './foo'
    const starMatch = line.match(/^export\s*\*\s+from\s+['"]([^'"]+)['"]/);
    if (starMatch) {
      const resolved = resolveImport(starMatch[1], barrelPath, aliases);
      if (!resolved || isIconPath(resolved)) continue;

      const resolvedContent = safeRead(resolved);
      if (isBarrelFile(resolved, resolvedContent)) {
        // Recurse into nested barrel
        const nested = getBarrelExports(resolved, aliases, newVisited);
        for (const [sym, src] of nested) result.set(sym, src);
      } else {
        // Direct source file — collect all its exports
        for (const sym of getDirectExports(resolved)) {
          result.set(sym, resolved);
        }
      }
      continue;
    }

    // export { A, B as C, default as D } from './foo'
    const namedMatch = line.match(/^export\s*\{([^}]+)\}\s+from\s+['"]([^'"]+)['"]/);
    if (namedMatch) {
      const resolved = resolveImport(namedMatch[2], barrelPath, aliases);
      if (!resolved || isIconPath(resolved)) continue;

      const symbols = namedMatch[1].split(",").map((s) => {
        const parts = s.trim().split(/\s+as\s+/);
        return {
          original: parts[0].trim(),
          exported: (parts[1] ?? parts[0]).trim(),
        };
      });

      for (const { original, exported } of symbols) {
        if (!exported || exported === "default") continue;
        // If re-exporting from another barrel, trace further
        const resolvedContent = safeRead(resolved);
        if (isBarrelFile(resolved, resolvedContent)) {
          const nested = getBarrelExports(resolved, aliases, newVisited);
          const trueSource = nested.get(original);
          if (trueSource) {
            result.set(exported, trueSource);
          } else {
            result.set(exported, resolved);
          }
        } else {
          result.set(exported, resolved);
        }
      }
    }
  }

  barrelCache.set(barrelPath, result);
  return result;
}

// Cache: absPath → Set<string> of directly-exported symbol names
const fileExportCache = new Map();

function getDirectExports(absPath) {
  if (fileExportCache.has(absPath)) return fileExportCache.get(absPath);

  const content = safeRead(absPath);
  const syms = new Set();

  for (const line of content.split("\n")) {
    const t = line.trim();

    // export [async] function/class/const/let/var/type/interface/enum Foo
    const directMatch = t.match(
      /^export\s+(?:default\s+)?(?:async\s+)?(?:abstract\s+)?(?:function\*?\s+|class\s+|const\s+|let\s+|var\s+|type\s+|interface\s+|enum\s+)(\w+)/
    );
    if (directMatch) syms.add(directMatch[1]);

    // export { A, B as C } (no 'from' — local re-export within file)
    const localNamed = t.match(/^export\s*\{([^}]+)\}(?!\s*from)/);
    if (localNamed) {
      for (const s of localNamed[1].split(",")) {
        const parts = s.trim().split(/\s+as\s+/);
        const name = (parts[1] ?? parts[0]).trim();
        if (name && name !== "default") syms.add(name);
      }
    }

    // export default function/class Foo (named)
    const defaultNamed = t.match(/^export\s+default\s+(?:function|class)\s+(\w+)/);
    if (defaultNamed) syms.add(defaultNamed[1]);
  }

  fileExportCache.set(absPath, syms);
  return syms;
}

// ─── Import path conversion ───────────────────────────────────────────────────

function toImportPath(absPath, fromFile, aliases) {
  // Prefer alias over relative (sorted longest first)
  const sortedAliases = Object.entries(aliases).sort(
    ([a], [b]) => b.length - a.length
  );
  for (const [prefix, absPrefix] of sortedAliases) {
    if (absPath.startsWith(absPrefix)) {
      const rel = absPath.slice(absPrefix.length);
      const clean = rel
        .replace(/\/index\.(ts|tsx)$/, "")
        .replace(/\.(ts|tsx)$/, "");
      return prefix + clean;
    }
  }

  // Fall back to relative
  let rel = relative(dirname(fromFile), absPath)
    .replace(/\.(ts|tsx)$/, "")
    .replace(/\/index$/, "");
  if (!rel.startsWith(".")) rel = "./" + rel;
  return rel;
}

// ─── File rewriting ───────────────────────────────────────────────────────────

/**
 * Collapse multi-line import statements into single lines so the main
 * matching regex can handle them uniformly.
 *
 * Handles patterns like:
 *   import {
 *     A,
 *     B,
 *   } from "specifier";
 */
function collapseMultiLineImports(lines) {
  const out = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    // Detect an import line that opens { but does NOT close } on the same line
    if (
      /^\s*import\s+(type\s+)?\{/.test(line) &&
      !line.includes("} from") &&
      !line.includes("} from")
    ) {
      // Collect lines until we find the closing } from "..."
      const parts = [line];
      let j = i + 1;
      while (j < lines.length) {
        parts.push(lines[j]);
        if (lines[j].includes("} from")) break;
        j++;
      }
      // Collapse: join symbol parts, strip newlines and extra spaces
      const joined = parts.join(" ").replace(/\s+/g, " ").trim();
      // Clean up whitespace inside braces: `{ A , B , C }` → `{ A, B, C }`
      const cleaned = joined.replace(/\{\s+/g, "{ ").replace(/\s+\}/g, " }").replace(/,\s+/g, ", ");
      out.push(cleaned);
      i = j + 1;
    } else {
      out.push(line);
      i++;
    }
  }
  return out;
}

function rewriteFile(filePath, barrelPaths, aliases) {
  const content = readFileSync(filePath, "utf8");
  // First collapse any multi-line imports to single lines
  const collapsedLines = collapseMultiLineImports(content.split("\n"));
  const lines = collapsedLines;
  const newLines = [];
  let changed = false;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    // Match single-line: import [type] { symbols } from "specifier"
    const m = line.match(
      /^(\s*)(import\s+(type\s+)?\{)([^}]*)\}\s+from\s+['"]([^'"]+)['"](\s*;?\s*)$/
    );

    if (m) {
      const [, indent, , isType, symbolsRaw, specifier] = m;
      const resolved = resolveImport(specifier, filePath, aliases);

      if (resolved && barrelPaths.has(resolved) && !isIconPath(resolved)) {
        const barrelExports = getBarrelExports(resolved, aliases);

        if (barrelExports.size > 0) {
          const symbols = symbolsRaw
            .split(",")
            .map((s) => {
              const t = s.trim();
              if (!t) return null;
              const parts = t.split(/\s+as\s+/);
              return {
                raw: t,
                name: parts[0].trim(),
                alias: parts[1]?.trim(),
              };
            })
            .filter(Boolean);

          // Group by source file
          const bySource = new Map(); // sourceAbsPath → symbols[]
          const unresolved = [];

          for (const sym of symbols) {
            const srcFile = barrelExports.get(sym.name);
            if (srcFile) {
              if (!bySource.has(srcFile)) bySource.set(srcFile, []);
              bySource.get(srcFile).push(sym);
            } else {
              unresolved.push(sym);
            }
          }

          if (bySource.size > 0) {
            const typePrefix = isType ? "type " : "";
            const replacement = [];

            for (const [srcFile, syms] of bySource) {
              const importPath = toImportPath(srcFile, filePath, aliases);
              const symList = syms
                .map((s) => (s.alias ? `${s.name} as ${s.alias}` : s.name))
                .join(", ");
              replacement.push(
                `${indent}import ${typePrefix}{ ${symList} } from "${importPath}";`
              );
            }

            if (unresolved.length > 0) {
              const symList = unresolved.map((s) => s.raw).join(", ");
              replacement.push(
                `${indent}import ${typePrefix}{ ${symList} } from "${specifier}"; // TODO: barrel-to-direct could not resolve source`
              );
            }

            newLines.push(...replacement);
            changed = true;
            continue;
          }
        }
      }
    }

    newLines.push(line);
  }

  if (changed) {
    const updated = newLines.join("\n");
    if (DRY_RUN) {
      console.log(
        `[DRY] ${relative(ROOT, filePath)} (${lines.length}→${newLines.length} lines)`
      );
    } else {
      writeFileSync(filePath, updated, "utf8");
      console.log(`Updated: ${relative(ROOT, filePath)}`);
    }
  }

  return changed;
}

// ─── Main ─────────────────────────────────────────────────────────────────────

let totalChanged = 0;
let totalBarrels = 0;
const stats = {};

for (const appName of APPS_TO_PROCESS) {
  const config = APP_CONFIGS[appName];
  if (!config) {
    console.error(`Unknown app: ${appName}`);
    continue;
  }

  console.log(`\n${"=".repeat(60)}`);
  console.log(`Processing: ${appName}`);
  console.log(`  srcDir: ${relative(ROOT, config.srcDir)}`);
  console.log("=".repeat(60));

  const allFiles = walkTs(config.srcDir);

  // Identify barrel files
  const barrelPaths = new Set();
  for (const f of allFiles) {
    const content = safeRead(f);
    if (isBarrelFile(f, content)) {
      barrelPaths.add(f);
      if (DRY_RUN) {
        console.log(`  [barrel] ${relative(ROOT, f)}`);
      }
    }
  }

  console.log(`Found ${barrelPaths.size} barrel files`);
  totalBarrels += barrelPaths.size;

  // Rewrite consumers
  let appChanged = 0;
  for (const f of allFiles) {
    if (barrelPaths.has(f)) continue; // skip barrel files themselves
    if (isIconPath(f)) continue;
    try {
      if (rewriteFile(f, barrelPaths, config.alias)) appChanged++;
    } catch (err) {
      console.error(`  Error: ${relative(ROOT, f)}: ${err.message}`);
    }
  }

  console.log(`${appName}: ${appChanged} consumer files updated`);
  stats[appName] = { barrels: barrelPaths.size, updated: appChanged };
  totalChanged += appChanged;
}

console.log(`\n${"=".repeat(60)}`);
console.log(`Summary:`);
for (const [app, s] of Object.entries(stats)) {
  console.log(`  ${app}: ${s.barrels} barrels, ${s.updated} consumers updated`);
}
console.log(`Total barrel files identified: ${totalBarrels}`);
console.log(`Total consumer files updated:  ${totalChanged}`);
if (DRY_RUN) console.log("\n(DRY RUN — no files were written)");
