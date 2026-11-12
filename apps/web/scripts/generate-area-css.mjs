#!/usr/bin/env node
/**
 * Generate each area bundle's Tailwind sources and HeroUI component sheets from the import graph.
 *
 * An area bundle (marketing, content, app) is imported by the routes it styles. Tailwind
 * emits only the classes of the files its @source lines name, and HeroUI v3 styles a
 * component only when its sheet is imported, so a hand-kept list drifts silently: a
 * route that renders a component from an unlisted folder ships it unstyled. This walks
 * every file those routes (and their layouts) reach and writes the exact list to
 * src/app/styles/generated/<area>.css. `--check` fails when a committed file is stale.
 */
import fs from "node:fs";
import { isBuiltin } from "node:module";
import path from "node:path";
import { parseSync } from "oxc-parser";
import { ResolverFactory } from "oxc-resolver";

const WEB = path.resolve(import.meta.dirname, "..");
const SRC = path.join(WEB, "src");
const APP = path.join(SRC, "app");
const STYLES = path.join(APP, "styles");
const OUT = path.join(STYLES, "generated");
export const AREAS = ["marketing", "content", "app"];
const ROUTE_FILES = ["layout", "template", "loading", "error", "not-found"];
const ROUTE_FILE = /^(?:page|layout|template|loading|error|not-found|default|route)\.tsx?$/;
const CODE = /\.(?:tsx?|jsx?|mjs)$/;
const HEROUI_REACT = "@heroui/react";
const HEROUI_STYLES = "@heroui/styles";

const resolver = new ResolverFactory({
  tsconfig: { configFile: path.join(WEB, "tsconfig.json"), references: "auto" },
  extensions: [".tsx", ".ts", ".jsx", ".js", ".mjs"],
  conditionNames: ["import", "default"],
  mainFields: ["module", "main"],
});

function resolveFrom(file, specifier) {
  const { path: resolved, error } = resolver.sync(path.dirname(file), specifier);
  if (error) throw new Error(`generate-area-css: cannot resolve "${specifier}" from ${path.relative(WEB, file)}: ${error}`);
  return resolved;
}

function parseModule(file) {
  const result = parseSync(file, fs.readFileSync(file, "utf8"));
  if (result.errors.length) throw new Error(`generate-area-css: ${path.relative(WEB, file)} does not parse: ${result.errors[0].message}`);
  return { module: result.module, code: fs.readFileSync(file, "utf8") };
}

/** Every runtime edge of a module: specifier plus the names it takes (null = whole module). */
function edges(file) {
  const { module, code } = parseModule(file);
  const out = [];
  for (const imp of module.staticImports) {
    const runtime = imp.entries.filter((e) => !e.isType);
    if (imp.entries.length && !runtime.length) continue;
    out.push({ specifier: imp.moduleRequest.value, names: runtime.map((e) => e.importName.name ?? null) });
  }
  for (const exp of module.staticExports) {
    for (const e of exp.entries) {
      if (e.moduleRequest && !e.isType) out.push({ specifier: e.moduleRequest.value, names: [e.importName.name ?? null] });
    }
  }
  for (const dyn of module.dynamicImports) {
    const literal = code.slice(dyn.moduleRequest.start, dyn.moduleRequest.end);
    const m = literal.match(/^(["'`])([^"'`$]+)\1$/);
    if (!m) throw new Error(`generate-area-css: ${path.relative(WEB, file)} has a non-literal import(${literal}); name the module so its styles can be traced`);
    out.push({ specifier: m[2], names: [null] });
  }
  return out;
}

function walkDir(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const p = path.join(dir, e.name);
    return e.isDirectory() ? walkDir(p) : [p];
  });
}

/** The route files that import styles/<area>.css, the routes under such a layout, and every layout-level file above them. */
export function areaEntries(area) {
  const marker = new RegExp(`import\\s+["'](?:\\.\\./)+styles/${area}\\.css["']`);
  const pages = walkDir(APP).filter((f) => CODE.test(f) && marker.test(fs.readFileSync(f, "utf8")));
  if (!pages.length) throw new Error(`generate-area-css: no route imports styles/${area}.css`);
  const entries = new Set(pages);
  // A layout's stylesheet styles every route below it.
  for (const page of pages.filter((f) => /^(?:layout|template)\.tsx?$/.test(path.basename(f)))) {
    for (const f of walkDir(path.dirname(page))) if (ROUTE_FILE.test(path.basename(f))) entries.add(f);
  }
  for (const page of pages) {
    for (let dir = path.dirname(page); dir.startsWith(APP); dir = path.dirname(dir)) {
      for (const name of ROUTE_FILES) {
        for (const ext of [".tsx", ".ts"]) {
          const candidate = path.join(dir, name + ext);
          if (fs.existsSync(candidate)) entries.add(candidate);
        }
      }
    }
  }
  return [...entries];
}

/** Source files the entries reach, and the HeroUI exports they use. */
function reach(entries) {
  const files = new Set();
  const heroui = new Set();
  const stack = [...entries];
  while (stack.length) {
    const file = stack.pop();
    if (files.has(file)) continue;
    files.add(file);
    for (const { specifier, names } of edges(file)) {
      if (specifier === HEROUI_REACT || specifier === HEROUI_STYLES) {
        for (const name of names) if (name) heroui.add(name);
        continue;
      }
      if (isBuiltin(specifier) || /\.(?:css|svg|png|jpe?g|webp|gif|json|mdx?|txt|woff2?)$/.test(specifier)) continue;
      const resolved = resolveFrom(file, specifier);
      if (resolved.startsWith(SRC) && CODE.test(resolved)) stack.push(resolved);
    }
  }
  return { files, heroui };
}

/** HeroUI style variant name -> its component sheet, read from @heroui/styles itself. */
function variantSheets() {
  const stylesIndex = resolveFrom(path.join(SRC, "x.ts"), HEROUI_STYLES);
  const components = path.join(path.dirname(stylesIndex), "components");
  const sheets = new Map();
  for (const dir of fs.readdirSync(components, { withFileTypes: true })) {
    if (!dir.isDirectory()) continue;
    const index = path.join(components, dir.name, "index.js");
    if (!fs.existsSync(index)) continue;
    for (const exp of parseModule(index).module.staticExports) {
      for (const e of exp.entries) if (e.exportName.name?.endsWith("Variants")) sheets.set(e.exportName.name, dir.name);
    }
  }
  return { sheets, components };
}

/** The variants a HeroUI export renders with, following @heroui/react's own module graph. */
function makeVariantTracer() {
  const reactIndex = resolveFrom(path.join(SRC, "x.ts"), HEROUI_REACT);
  const exportsOf = new Map();
  for (const exp of parseModule(reactIndex).module.staticExports) {
    for (const e of exp.entries) if (e.moduleRequest) exportsOf.set(e.exportName.name, e.moduleRequest.value);
  }
  const cache = new Map();
  const variantsOfModule = (file, seen = new Set()) => {
    if (cache.has(file)) return cache.get(file);
    if (seen.has(file)) return new Set();
    seen.add(file);
    const found = new Set();
    for (const { specifier, names } of edges(file)) {
      if (specifier === HEROUI_STYLES) for (const n of names) if (n?.endsWith("Variants")) found.add(n);
      if (specifier.startsWith(".")) for (const v of variantsOfModule(path.resolve(path.dirname(file), specifier), seen)) found.add(v);
    }
    cache.set(file, found);
    return found;
  };
  return (name) => {
    if (name.endsWith("Variants")) return new Set([name]);
    const from = exportsOf.get(name);
    if (!from) throw new Error(`generate-area-css: ${HEROUI_REACT} has no export "${name}"`);
    if (from === HEROUI_STYLES) return new Set();
    return variantsOfModule(path.resolve(path.dirname(reactIndex), from));
  };
}

export function renderArea(area) {
  const { files, heroui } = reach(areaEntries(area));
  const { sheets, components } = variantSheets();
  const variantsOf = makeVariantTracer();
  const used = new Set();
  for (const name of heroui) {
    for (const variant of variantsOf(name)) {
      const sheet = sheets.get(variant);
      if (!sheet) throw new Error(`generate-area-css: no @heroui/styles component exports ${variant} (used by ${name})`);
      if (fs.existsSync(path.join(components, `${sheet}.css`))) used.add(sheet);
    }
  }
  // Shallow directories first: Tailwind drops a file @source when a later one sits in an ancestor directory.
  const depth = (f) => f.split(path.sep).length;
  const sources = [...files]
    .sort((a, b) => depth(a) - depth(b) || a.localeCompare(b))
    .map((f) => path.relative(OUT, f).split(path.sep).join("/"));
  return [
    `/* @generated by scripts/generate-area-css.mjs from the routes that import styles/${area}.css. Run \`pnpm area-css\`; do not edit. */`,
    ...[...used].sort().map((s) => `@import "@heroui/styles/components/${s}.css" layer(components);`),
    "",
    ...sources.map((s) => `@source "${s}";`),
    "",
  ].join("\n");
}

function main() {
  const check = process.argv.includes("--check");
  fs.mkdirSync(OUT, { recursive: true });
  const stale = [];
  for (const area of AREAS) {
    const file = path.join(OUT, `${area}.css`);
    const next = renderArea(area);
    const current = fs.existsSync(file) ? fs.readFileSync(file, "utf8") : null;
    if (current === next) continue;
    if (check) stale.push(path.relative(WEB, file));
    else fs.writeFileSync(file, next);
  }
  if (stale.length) {
    console.error(`generate-area-css: stale ${stale.join(", ")}; run \`pnpm area-css\` and commit the result`);
    process.exit(1);
  }
}

if (import.meta.url === `file://${process.argv[1]}`) main();
