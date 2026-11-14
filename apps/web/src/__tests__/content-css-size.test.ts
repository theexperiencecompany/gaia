/**
 * The content sheet styles the programmatic families (learn, compare, alternative-to,
 * automate, the best-of and persona guides), several thousand pages, so it stays under
 * squirrelscan's 150 KB render-blocking CSS line. It passed 197 KB while the marketplace
 * and blog, whose search, filter and share menus no family page renders, shared it.
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import tailwind from "@tailwindcss/postcss";
import postcss from "postcss";
import { describe, expect, it } from "vitest";

const CONTENT_SHEET = path.resolve(__dirname, "../app/styles/content.css");
// squirrel 0.0.133 perf/css-file-size: CSS_WARN_BYTES.
const CSS_WARN_BYTES = 150 * 1024;

describe("content area stylesheet", () => {
  it("compiles under 150 KB minified", async () => {
    const result = await postcss([
      tailwind({ optimize: { minify: true } }),
    ]).process(readFileSync(CONTENT_SHEET, "utf8"), { from: CONTENT_SHEET });
    expect(result.css.length).toBeLessThan(CSS_WARN_BYTES);
  });
});
