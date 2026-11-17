/**
 * A class string that lives in @shared (libs/shared/ts) reaches the area sheet of the routes
 * that render it. The tool icon colours (tool-icon-config.ts iconColor) were never compiled:
 * the generator followed imports only under apps/web/src, so the marketplace's workflow
 * cards drew the Reddit and Todos icons grey.
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import tailwind from "@tailwindcss/postcss";
import postcss from "postcss";
import { describe, expect, it } from "vitest";

const STYLES = path.resolve(__dirname, "../app/styles");

async function compiled(area: string): Promise<string> {
  const from = path.join(STYLES, `${area}.css`);
  const result = await postcss([tailwind()]).process(
    readFileSync(from, "utf8"),
    { from },
  );
  return result.css;
}

describe("area sheets compile @shared class strings", () => {
  it.each(["directory", "app"])(
    "%s.css styles the Reddit tool icon colour",
    async (area) => {
      expect(await compiled(area)).toContain(String.raw`.text-\[\#FF4500\]`);
    },
  );
});
