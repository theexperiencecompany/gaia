import { execFileSync } from "node:child_process";
import {
  existsSync,
  globSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import path from "node:path";
import tailwind from "@tailwindcss/postcss";
import postcss from "postcss";
import { describe, expect, it } from "vitest";
import { AREAS } from "../../scripts/generate-area-css.mjs";

/**
 * Tailwind v4 resolves `@source` globs relative to the CSS file and silently
 * emits nothing when one matches no files. A path that goes stale — as every
 * `../../../../../node_modules/...` glob did when pnpm's hoisted linker was
 * dropped (#1132) — costs hundreds of HeroUI utilities with no build error.
 */
const generated = (area: string) => `src/app/styles/generated/${area}.css`;

// base.css plus each area bundle are the stylesheets that ship.
const STYLESHEETS = [
  "src/app/styles/base.css",
  ...AREAS.map(generated),
  "../mobile/global.css",
];

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
    execFileSync(
      process.execPath,
      ["scripts/generate-area-css.mjs", "--check"],
      {
        cwd: WEB_DIR,
        stdio: "pipe",
      },
    );
  });

  for (const area of AREAS) {
    it(`${area}.css styles its routes through generated/${area}.css only`, () => {
      const css = readFileSync(
        path.join(WEB_DIR, `src/app/styles/${area}.css`),
        "utf8",
      );
      expect(css).toContain(`@import "./generated/${area}.css";`);
      expect(css).not.toMatch(SOURCE_PATH);
      expect(css).not.toContain("@heroui/styles/components/");
    });

    // Tailwind 4.3 drops a file @source when a later one sits in an ancestor directory (canary below).
    it(`generated/${area}.css lists no file after one in a deeper directory`, () => {
      const dirs = declaredSources(generated(area)).map((file) =>
        path.dirname(file),
      );
      dirs.forEach((dir, i) => {
        const shadowed = dirs
          .slice(0, i)
          .find((earlier) => earlier.startsWith(`${dir}${path.sep}`));
        expect(shadowed, `${dir} is listed after ${shadowed}`).toBeUndefined();
      });
    });
  }
});

const requireFromWeb = createRequire(import.meta.url);
const THEME_CSS = requireFromWeb.resolve("tailwindcss/theme.css");
const UTILITIES_CSS = requireFromWeb.resolve("tailwindcss/utilities.css");

/** The classes Tailwind emits for two file @source lines, the deeper file first or last. */
async function emittedWithDeepFile(order: "first" | "last"): Promise<string> {
  const dir = mkdtempSync(path.join(tmpdir(), "tw-source-order-"));
  try {
    mkdirSync(path.join(dir, "a/b"), { recursive: true });
    writeFileSync(
      path.join(dir, "a/b/deep.tsx"),
      '<i className="text-red-500" />',
    );
    writeFileSync(
      path.join(dir, "a/shallow.tsx"),
      '<i className="text-blue-500" />',
    );
    const sources = ['@source "./a/b/deep.tsx";', '@source "./a/shallow.tsx";'];
    if (order === "last") sources.reverse();
    const css = [
      `@import "${THEME_CSS}";`,
      `@import "${UTILITIES_CSS}" source(none);`,
      ...sources,
    ].join("\n");
    const from = path.join(dir, "entry.css");
    return (await postcss([tailwind({ base: dir })]).process(css, { from }))
      .css;
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

// Canary for the depth sort in generate-area-css.mjs. When this goes red, Tailwind
// fixed the bug: delete the sort and the ordering test above, then this canary.
describe("Tailwind's @source ancestor-directory bug", () => {
  it("still drops a deep file listed before a file in its ancestor directory", async () => {
    expect(await emittedWithDeepFile("first")).not.toContain(".text-red-500");
    expect(await emittedWithDeepFile("last")).toContain(".text-red-500");
  });
});
