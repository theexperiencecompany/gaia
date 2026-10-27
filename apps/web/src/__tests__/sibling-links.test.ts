/** Every blog post and role page is linked from at least two of its siblings, so none is reachable only from its hub. */
import type { ReactElement } from "react";
import { describe, expect, it } from "vitest";

import BlogPostPage from "@/app/[locale]/(landing)/blog/[slug]/page";
import { getRelatedPersonas } from "@/features/personas/data/getTranslatedPersona";
import { getAllPersonaSlugs } from "@/features/personas/data/personasData";
import { getAllBlogSlugs } from "@/lib/blog";

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
});
