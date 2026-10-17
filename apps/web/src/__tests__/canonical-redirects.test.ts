/**
 * Canonical-redirect drift guard: the routing table in
 * `apps/web/canonical-redirects.mjs` must match the victim markers in
 * `public/data/* /{victim}.json`, victims must stay out of the live page set
 * (`_slugs.json`), and every pair must expand to locale-preserving 308s.
 *
 * Contract under test:
 * - JSON markers say "this page defers to X" (`canonicalSlug` for
 *   same-family glossary/combos, `canonicalPath` for cross-family
 *   compare/alternatives).
 * - `_slugs.json` per family is the live page set — victims excluded, so the
 *   sitemap, llms.txt, feeds, hubs and related-lists never emit them.
 * - `canonical-redirects.mjs` says the same thing to the router (308,
 *   locale-preserving). Victim pages never render, so every rendered page
 *   self-canonicalizes and emits full hreflang.
 * - `public/data/i18n/*` overlays are intentionally out of scope: victim
 *   content stays there (translation overlays are keyed by slug, not linked).
 */
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { defaultLocale, locales } from "@/i18n/config";

import {
  CANONICAL_REDIRECT_PAIRS,
  expandCanonicalRedirects,
} from "../../canonical-redirects.mjs";

const DATA_DIR = path.join(process.cwd(), "public", "data");

const FAMILIES = {
  combos: "/automate/",
  glossary: "/learn/",
  comparisons: "/compare/",
  alternatives: "/alternative-to/",
} as const;

type Family = keyof typeof FAMILIES;

interface VictimMarker {
  victimPath: string;
  winnerPath: string;
}

/** Derive every victim→winner pair from the JSON markers on disk. */
function readMarkersFromData(): VictimMarker[] {
  const markers: VictimMarker[] = [];
  for (const [family, dir] of Object.entries(FAMILIES)) {
    const familyDir = path.join(DATA_DIR, family);
    for (const file of fs.readdirSync(familyDir)) {
      if (!file.endsWith(".json") || file === "_slugs.json") continue;
      const slug = file.replace(/\.json$/, "");
      const entry = JSON.parse(
        fs.readFileSync(path.join(familyDir, file), "utf8"),
      ) as { canonicalSlug?: string; canonicalPath?: string };
      const marker = entry.canonicalSlug ?? entry.canonicalPath;
      if (!marker) continue;
      markers.push({
        victimPath: `${dir}${slug}`,
        winnerPath: marker.startsWith("/") ? marker : `${dir}${marker}`,
      });
    }
  }
  return markers;
}

/**
 * The 7 duplicate pairs consolidated by the GSC audit (2026-07-19 →
 * 2026-10-17, `data_state: all`, property `sc-domain:heygaia.io`): each
 * winner is the higher-impression canonical. Pinned here so a future edit
 * that flips a pair fails loudly.
 */
const TASK_PAIRS: ReadonlyArray<readonly [string, string]> = [
  ["/automate/teams-slack", "/automate/slack-teams"],
  ["/automate/trello-notion", "/automate/notion-trello"],
  ["/alternative-to/superhuman", "/compare/superhuman"],
  ["/compare/limitless-ai", "/alternative-to/limitless-ai"],
  ["/compare/sunsama", "/alternative-to/sunsama"],
  ["/alternative-to/shortwave", "/compare/shortwave"],
  ["/learn/mcp-model-context-protocol", "/learn/model-context-protocol"],
];

describe("canonical redirects", () => {
  it("contains all 7 consolidated pairs with the chosen canonicals", () => {
    for (const [victim, winner] of TASK_PAIRS) {
      expect(CANONICAL_REDIRECT_PAIRS).toContainEqual([victim, winner]);
    }
  });

  it("table matches the JSON victim markers exactly (no drift either way)", () => {
    const markers = readMarkersFromData();
    expect(markers.length).toBeGreaterThan(0);
    for (const { victimPath, winnerPath } of markers) {
      expect(CANONICAL_REDIRECT_PAIRS).toContainEqual([victimPath, winnerPath]);
    }
    const markerKeys = new Set(markers.map((m) => `${m.victimPath}`));
    for (const [from, to] of CANONICAL_REDIRECT_PAIRS) {
      expect(markerKeys.has(from)).toBe(true);
      const marker = markers.find((m) => m.victimPath === from);
      expect(marker?.winnerPath).toBe(to);
    }
  });

  it("excludes every victim slug from the live page set (_slugs.json)", () => {
    const markers = readMarkersFromData();
    for (const family of Object.keys(FAMILIES) as Family[]) {
      const slugs = JSON.parse(
        fs.readFileSync(path.join(DATA_DIR, family, "_slugs.json"), "utf8"),
      ) as string[];
      const slugSet = new Set(slugs);
      for (const { victimPath } of markers.filter((m) =>
        m.victimPath.startsWith(FAMILIES[family]),
      )) {
        const victimSlug = victimPath.slice(FAMILIES[family].length);
        expect(slugSet.has(victimSlug)).toBe(false);
      }
    }
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
    for (const [from, to] of TASK_PAIRS) {
      expect(rows).toContainEqual({
        source: from,
        destination: to,
        permanent: true,
      });
    }
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
