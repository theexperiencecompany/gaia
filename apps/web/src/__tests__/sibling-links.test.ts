/** Every blog post, role page, comparison, alternative and automation combo is linked from at least two of its siblings, so none is reachable only from its hub. */
import type { ReactElement } from "react";
import { describe, expect, it } from "vitest";

import BlogPostPage from "@/app/[locale]/(landing)/blog/[slug]/page";
import { getAllAlternatives } from "@/features/alternatives/data/alternativesData";
import { comparisonCategoryOf } from "@/features/comparisons/data/comparisonCategories";
import { getAllComparisons } from "@/features/comparisons/data/comparisonsData";
import { getAllCombos } from "@/features/integrations/data/combosData";
import { comboAppsOf } from "@/features/integrations/lib/comboApps";
import { relatedComboRows } from "@/features/integrations/lib/relatedCombos";
import { getRelatedPersonas } from "@/features/personas/data/getTranslatedPersona";
import { getAllPersonaSlugs } from "@/features/personas/data/personasData";
import { getAllBlogSlugs } from "@/lib/blog";
import { relatedInGroup } from "@/lib/relatedInGroup";

const MIN_SIBLING_LINKS = 2;

/** How many times each slug is linked, given every page's outgoing sibling links. */
function inboundCounts(
  slugs: readonly string[],
  linksFrom: ReadonlyMap<string, readonly string[]>,
): Map<string, number> {
  const counts = new Map(slugs.map((slug) => [slug, 0]));
  for (const [from, targets] of linksFrom) {
    for (const target of targets) {
      if (target === from) throw new Error(`${from} links itself`);
      counts.set(target, (counts.get(target) ?? 0) + 1);
    }
  }
  return counts;
}

function underLinked(counts: Map<string, number>): string[] {
  return [...counts].flatMap(([slug, count]) =>
    count < MIN_SIBLING_LINKS ? [`${slug}: ${count}`] : [],
  );
}

describe("sibling links", () => {
  it("suggests every blog post from at least two other posts", async () => {
    const slugs = await getAllBlogSlugs();
    const linksFrom = new Map<string, string[]>();
    for (const slug of slugs) {
      const page = (await BlogPostPage({
        params: Promise.resolve({ slug }),
      })) as ReactElement<{ suggestedPosts: { slug: string }[] }>;
      linksFrom.set(
        slug,
        page.props.suggestedPosts.map((post) => post.slug),
      );
    }
    expect(underLinked(inboundCounts(slugs, linksFrom))).toEqual([]);
  });

  it("links every role page from at least two other role pages", async () => {
    const slugs = await getAllPersonaSlugs();
    const linksFrom = new Map<string, string[]>();
    for (const slug of slugs) {
      const related = await getRelatedPersonas(slug, "de");
      linksFrom.set(
        slug,
        related.map((persona) => persona.slug),
      );
    }
    expect(underLinked(inboundCounts(slugs, linksFrom))).toEqual([]);
  });

  it("links every automation combo from at least two combos that share an app", async () => {
    const combos = await getAllCombos();
    const linksFrom = new Map<string, string[]>();
    for (const combo of combos) {
      const rows = relatedComboRows(combo, combos);
      const related = rows.flatMap((row) => row.combos);
      for (const row of rows) {
        for (const other of row.combos) {
          expect(comboAppsOf(other).map((app) => app.slug)).toContain(
            row.app.slug,
          );
        }
      }
      linksFrom.set(
        combo.slug,
        related.map((other) => other.slug),
      );
    }
    expect(
      underLinked(
        inboundCounts(
          combos.map((combo) => combo.slug),
          linksFrom,
        ),
      ),
    ).toEqual([]);
  });

  it.each([
    ["comparison", getAllComparisons, comparisonCategoryOf],
    [
      "alternative",
      getAllAlternatives,
      (alternative: { category: string }) => alternative.category,
    ],
  ] as const)(
    "suggests every %s from at least two others in its category",
    async (_kind, load, groupOf) => {
      const items = await load();
      const linksFrom = new Map<string, string[]>();
      for (const item of items) {
        linksFrom.set(
          item.slug,
          relatedInGroup(
            items,
            item.slug,
            groupOf as (i: typeof item) => string,
          ).map((other) => other.slug),
        );
      }
      expect(
        underLinked(
          inboundCounts(
            items.map((item) => item.slug),
            linksFrom,
          ),
        ),
      ).toEqual([]);
    },
  );
});
