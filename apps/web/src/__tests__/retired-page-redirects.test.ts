import { globSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import {
  expandCanonicalRedirects,
  RETIRED_PAGE_PAIRS,
} from "../../canonical-redirects.mjs";

const LOCALE_DIR = path.join(process.cwd(), "src/app/[locale]");

/** Route paths of every page under [locale], with route groups stripped. */
function routes(): Set<string> {
  return new Set(
    globSync("**/page.tsx", { cwd: LOCALE_DIR }).map((file) => {
      const segments = path
        .dirname(file)
        .split(path.sep)
        .filter((segment) => segment !== "." && !/^\(.*\)$/.test(segment));
      return `/${segments.join("/")}`;
    }),
  );
}

describe("removed pages", () => {
  const redirects = expandCanonicalRedirects(RETIRED_PAGE_PAIRS);

  it.each([
    ["/notifications", "/c"],
    ["/blog/create", "/blog"],
  ])("%s forwards permanently to %s, in every locale", (from, to) => {
    expect(redirects).toContainEqual({
      source: from,
      destination: to,
      permanent: true,
    });
    expect(redirects).toContainEqual({
      source: `/de${from}`,
      destination: `/de${to}`,
      permanent: true,
    });
  });

  it("are gone, and forward to a page that exists", () => {
    const pages = routes();
    for (const [from, to] of RETIRED_PAGE_PAIRS) {
      expect(pages.has(from), `${from} still has a page`).toBe(false);
      expect(pages.has(to), `${to} has no page`).toBe(true);
    }
  });
});
