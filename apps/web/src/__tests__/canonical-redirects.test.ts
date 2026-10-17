/**
 * Canonical-redirect contract: `apps/web/canonical-redirects.mjs` is the one
 * source of truth for consolidated near-duplicates. Each victim stays out of
 * the live page set (`_slugs.json`), each winner is a live page (so there are
 * no chains), and every pair expands to locale-preserving 308s.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { defaultLocale, locales } from "@/i18n/config";
import { canonicalHref, isRedirectedPath } from "@/lib/canonicalLinks";

import {
  CANONICAL_REDIRECT_PAIRS,
  expandCanonicalRedirects,
} from "../../canonical-redirects.mjs";

const DATA_DIR = path.join(process.cwd(), "public", "data");

const FAMILY_BY_PREFIX: Record<string, string> = {
  "/for/": "personas",
  "/automate/": "combos",
  "/learn/": "glossary",
  "/compare/": "comparisons",
  "/alternative-to/": "alternatives",
};

/** The live page set for a path's data-driven family, or undefined for a route outside those families. */
function liveSlugsFor(
  pagePath: string,
): { slug: string; live: Set<string> } | undefined {
  const prefix = Object.keys(FAMILY_BY_PREFIX).find((p) =>
    pagePath.startsWith(p),
  );
  if (prefix === undefined) return undefined;
  const slugs = JSON.parse(
    fs.readFileSync(
      path.join(DATA_DIR, FAMILY_BY_PREFIX[prefix], "_slugs.json"),
      "utf8",
    ),
  ) as string[];
  return { slug: pagePath.slice(prefix.length), live: new Set(slugs) };
}

describe("canonical redirects", () => {
  it("keeps every victim out of the live page set", () => {
    for (const [victim] of CANONICAL_REDIRECT_PAIRS) {
      const family = liveSlugsFor(victim);
      if (family === undefined) {
        // A route victim must not still exist as a page the redirect shadows.
        const pageFile = path.join(
          process.cwd(),
          "src/app/[locale]/(landing)",
          victim,
          "page.tsx",
        );
        expect(fs.existsSync(pageFile), pageFile).toBe(false);
        continue;
      }
      expect(family.live.has(family.slug), victim).toBe(false);
    }
  });

  it("points every victim at a live page, never another victim", () => {
    for (const [victim, winner] of CANONICAL_REDIRECT_PAIRS) {
      const family = liveSlugsFor(winner);
      if (family !== undefined) {
        expect(family.live.has(family.slug), `${victim} -> ${winner}`).toBe(
          true,
        );
      }
      expect(isRedirectedPath(winner), winner).toBe(false);
    }
  });

  it("resolves a victim link to its winner and leaves live paths alone", () => {
    expect(canonicalHref("/compare/sunsama")).toBe("/alternative-to/sunsama");
    expect(canonicalHref("/automate/teams-slack")).toBe(
      "/automate/slack-teams",
    );
    expect(canonicalHref("/compare/notion")).toBe("/compare/notion");
  });

  it("expands every pair to unprefixed + all locale prefixes, permanent (308)", () => {
    const rows = expandCanonicalRedirects();
    expect(rows).toHaveLength(CANONICAL_REDIRECT_PAIRS.length * 7);
    for (const row of rows) {
      expect(row.permanent).toBe(true);
    }
    // Locale preservation spot-checks (unprefixed + one non-default locale).
    expect(rows).toContainEqual({
      source: "/automate/teams-slack",
      destination: "/automate/slack-teams",
      permanent: true,
    });
    expect(rows).toContainEqual({
      source: "/pt-BR/automate/teams-slack",
      destination: "/pt-BR/automate/slack-teams",
      permanent: true,
    });
    expect(rows).toContainEqual({
      source: "/ja/compare/limitless-ai",
      destination: "/ja/alternative-to/limitless-ai",
      permanent: true,
    });
  });

  it("locale prefixes mirror the i18n config (en default unprefixed)", () => {
    const nonDefault = (locales as readonly string[]).filter(
      (locale) => locale !== defaultLocale,
    );
    const [from, to] = CANONICAL_REDIRECT_PAIRS[0];
    const rows = expandCanonicalRedirects([[from, to]]);
    expect(rows).toHaveLength(1 + nonDefault.length);
    expect(rows[0]).toEqual({ source: from, destination: to, permanent: true });
    for (const locale of nonDefault) {
      expect(rows).toContainEqual({
        source: `/${locale}${from}`,
        destination: `/${locale}${to}`,
        permanent: true,
      });
    }
  });
});
