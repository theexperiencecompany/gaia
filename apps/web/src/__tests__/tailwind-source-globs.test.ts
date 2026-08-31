import { globSync, readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Tailwind v4 resolves `@source` globs relative to the CSS file and silently
 * emits nothing when one matches no files. A path that goes stale — as every
 * `../../../../../node_modules/...` glob did when pnpm's hoisted linker was
 * dropped (#1132) — costs hundreds of HeroUI utilities with no build error.
 */
const STYLESHEETS = [
  "src/app/styles/globals.css",
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

describe("Tailwind @source globs", () => {
  for (const stylesheet of STYLESHEETS) {
    it(`${stylesheet}: every declared source matches at least one file`, () => {
      const sources = declaredSources(stylesheet);
      expect(sources.length).toBeGreaterThan(0);

      for (const source of sources) {
        expect(
          globSync(source),
          `no files match @source "${source}"`,
        ).not.toHaveLength(0);
      }
    });
  }
});
