/** robots.txt keeps crawlers out of the signed-in app and never out of a page the sitemap asks them to index. */
import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { getSitemapEntries } from "@/lib/sitemapData";

const ROBOTS = readFileSync(
  path.join(process.cwd(), "public", "robots.txt"),
  "utf8",
);

/** Disallow rules as Google reads them: a path prefix, `*` any run, `$` the end. */
const DISALLOW = ROBOTS.split("\n")
  .filter((line) => line.startsWith("Disallow:"))
  .map((line) => line.slice("Disallow:".length).trim())
  .map((rule) => {
    const pattern = rule
      .replace(/[.+?^{}()|[\]\\]/g, "\\$&")
      .replaceAll("*", ".*");
    return { rule, matches: new RegExp(`^${pattern}`) };
  });

function blockingRule(url: string): string | undefined {
  const { pathname } = new URL(url);
  return DISALLOW.find(({ matches }) => matches.test(pathname))?.rule;
}

/** Sitemap shards built from local data only (no backend): static pages and the programmatic families. */
const LOCAL_SHARDS = [0, 5, 6, 7, 8, 9];

describe("robots.txt", () => {
  it("blocks the signed-in app", () => {
    for (const url of [
      "https://heygaia.io/c/123",
      "https://heygaia.io/c",
      "https://heygaia.io/todos",
      "https://heygaia.io/settings/account",
    ]) {
      expect(blockingRule(url), url).toBeDefined();
    }
  });

  it("blocks no page the sitemap lists", async () => {
    const entries = (
      await Promise.all(LOCAL_SHARDS.map((id) => getSitemapEntries(id)))
    ).flat();
    expect(entries.length).toBeGreaterThan(1000);
    for (const { url } of entries) {
      expect(blockingRule(url), url).toBeUndefined();
    }
  });
});
