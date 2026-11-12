import { execFileSync } from "node:child_process";
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
  "src/app/styles/generated/marketing.css",
  "src/app/styles/generated/content.css",
  "src/app/styles/generated/app.css",
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
const AREAS = ["marketing", "content", "app"] as const;
const generated = (area: string) => `src/app/styles/generated/${area}.css`;
const MUST_DECLARE_SOURCES = new Set<string>(AREAS.map(generated));

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

const WEB_DIR = path.resolve(__dirname, "../..");

describe("area bundles come from the import graph", () => {
  it("the committed generated/<area>.css files match the routes that import each area", () => {
    // Throws with the generator's stderr when a route's reach changed without `pnpm area-css`.
    execFileSync(process.execPath, ["scripts/generate-area-css.mjs", "--check"], {
      cwd: WEB_DIR,
      stdio: "pipe",
    });
  });

  for (const area of AREAS) {
    it(`${area}.css styles its routes through generated/${area}.css only`, () => {
      const css = readFileSync(path.join(WEB_DIR, `src/app/styles/${area}.css`), "utf8");
      expect(css).toContain(`@import "./generated/${area}.css";`);
      expect(css).not.toMatch(SOURCE_PATH);
      expect(css).not.toContain("@heroui/styles/components/");
    });

    // Tailwind 4.3 drops a file @source when a later one sits in an ancestor directory.
    it(`generated/${area}.css lists no file after one in a deeper directory`, () => {
      const dirs = declaredSources(generated(area)).map((file) => path.dirname(file));
      dirs.forEach((dir, i) => {
        const shadowed = dirs.slice(0, i).find((earlier) => earlier.startsWith(`${dir}${path.sep}`));
        expect(shadowed, `${dir} is listed after ${shadowed}`).toBeUndefined();
      });
    });
  }
});
