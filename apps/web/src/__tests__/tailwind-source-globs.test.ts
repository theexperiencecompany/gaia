import { globSync, readFileSync } from "node:fs";
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
          globSync(source),
          `no files match @source "${source}"`,
        ).not.toHaveLength(0);
      }
    });
  }
});
