/** Every guide in the data has the route that serves it, and every guide route loads the data file it names. */
import { existsSync, readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { getGuide } from "@/features/guides/data/guidesData";

const GUIDES_DIR = path.join(process.cwd(), "public", "data", "guides");
const LANDING_DIR = path.join(
  process.cwd(),
  "src",
  "app",
  "[locale]",
  "(landing)",
);
const GUIDE_SLUG_DECLARATION = /const SLUG = "([^"]+)";/;

const slugs: string[] = JSON.parse(
  readFileSync(path.join(GUIDES_DIR, "_slugs.json"), "utf8"),
);

function guideRouteSlugs(): string[] {
  return readdirSync(LANDING_DIR).flatMap((dir) => {
    const page = path.join(LANDING_DIR, dir, "page.tsx");
    if (!existsSync(page)) return [];
    const source = readFileSync(page, "utf8");
    if (!source.includes("@/components/seo/GuideLanding")) return [];
    const declared = GUIDE_SLUG_DECLARATION.exec(source)?.[1];
    expect(declared, `${dir}/page.tsx names its own directory`).toBe(dir);
    return [dir];
  });
}

describe("guide pages", () => {
  it("lists exactly the guide routes in _slugs.json", () => {
    expect([...guideRouteSlugs()].sort()).toEqual([...slugs].sort());
  });

  it.each(slugs)("loads %s with its own slug", async (slug) => {
    const guide = await getGuide(slug);
    expect(guide.slug).toBe(slug);
  });

  it("fails loudly for a guide with no data file", async () => {
    await expect(getGuide("no-such-guide")).rejects.toThrow(
      "public/data/guides/no-such-guide.json",
    );
  });
});
