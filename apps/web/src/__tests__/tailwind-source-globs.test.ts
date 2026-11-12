import { existsSync, globSync, readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Tailwind v4 resolves `@source` globs relative to the CSS file and silently
 * emits nothing when one matches no files. A path that goes stale — as every
 * `../../../../../node_modules/...` glob did when pnpm's hoisted linker was
 * dropped (#1132) — costs hundreds of HeroUI utilities with no build error.
 */
/**
 * The bundles that actually ship. `globals.css` is dead code and used to be the
 * only file this guard watched, so every real bundle could drift unchecked.
 * Keep this list in sync with the `import "...#.css"` calls in app/**.
 */
const STYLESHEETS = [
  "src/app/styles/base.css",
  "src/app/styles/marketing.css",
  "src/app/styles/content.css",
  "src/app/styles/app.css",
  "../mobile/global.css",
] as const;

const SOURCE_PATH = /@source\s+(?:not\s+)?"([^"]+)"/g;

function declaredSources(stylesheet: string): string[] {
  const file = path.resolve(__dirname, "../..", stylesheet);
  const css = readFileSync(file, "utf8");
  return [...css.matchAll(SOURCE_PATH)]
    .map(([, glob]) => glob)
    .filter((glob) => !glob.startsWith("inline("))
    .map((glob) => path.resolve(path.dirname(file), glob));
}

// base.css is the always-shipped floor and intentionally declares no file
// globs (it only pins @source inline utilities). The area bundles must declare
// real sources or they emit nothing for the routes that import them.
const MUST_DECLARE_SOURCES = new Set([
  "src/app/styles/marketing.css",
  "src/app/styles/content.css",
  "src/app/styles/app.css",
]);

describe("Tailwind @source globs", () => {
  for (const stylesheet of STYLESHEETS) {
    it(`${stylesheet}: every declared source matches at least one file`, () => {
      const sources = declaredSources(stylesheet);
      if (MUST_DECLARE_SOURCES.has(stylesheet)) {
        expect(sources.length).toBeGreaterThan(0);
      }

      for (const source of sources) {
        expect(
          existsSync(source) ? [source] : globSync(source),
          `no files match @source "${source}"`,
        ).not.toHaveLength(0);
      }
    });
  }
});

const APP_DIR = path.resolve(__dirname, "../app");
const SRC_DIR = path.resolve(__dirname, "..");
const AREA_IMPORT =
  /import\s+"(?:\.\.\/)+styles\/(marketing|content|app)\.css";/;
const COMPONENT_IMPORT = /from\s+"@\/((?:features|components)\/[^"]+)"/g;

interface SourceRule {
  negated: boolean;
  root: string;
}

function sourceRules(stylesheet: string): SourceRule[] {
  const file = path.resolve(__dirname, "../..", stylesheet);
  const css = readFileSync(file, "utf8");
  return [...css.matchAll(/@source\s+(not\s+)?"([^"]+)"/g)]
    .filter(([, , glob]) => !glob.startsWith("inline("))
    .map(([, negated, glob]) => ({
      negated: Boolean(negated),
      root: path.resolve(path.dirname(file), glob),
    }));
}

function isScanned(file: string, rules: SourceRule[]): boolean {
  const within = (root: string) =>
    file === root || file.startsWith(`${root}${path.sep}`);
  return (
    rules.some((rule) => !rule.negated && within(rule.root)) &&
    !rules.some((rule) => rule.negated && within(rule.root))
  );
}

// A route gets only the utilities its area bundle's @source globs scan; a route
// moved out of a scanned folder silently loses its own and its features' classes.
describe("area bundles scan the routes that import them", () => {
  const routes = globSync("**/{page,layout}.tsx", { cwd: APP_DIR });
  for (const route of routes) {
    const file = path.join(APP_DIR, route);
    const source = readFileSync(file, "utf8");
    const area = source.match(AREA_IMPORT)?.[1];
    if (!area) continue;
    it(`${route} is scanned by ${area}.css`, () => {
      const rules = sourceRules(`src/app/styles/${area}.css`);
      expect(isScanned(file, rules), `${area}.css skips ${route}`).toBe(true);
      for (const [, specifier] of source.matchAll(COMPONENT_IMPORT)) {
        const component = path.join(SRC_DIR, `${specifier}.tsx`);
        if (!existsSync(component)) continue;
        if (!readFileSync(component, "utf8").includes("className")) continue;
        expect(
          isScanned(component, rules),
          `${area}.css skips ${specifier}, which ${route} renders`,
        ).toBe(true);
      }
    });
  }
});
