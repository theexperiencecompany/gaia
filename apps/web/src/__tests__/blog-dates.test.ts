/** A revised blog post tells the sitemap and its own Article schema the same modification date. */
import type { ReactElement } from "react";
import type { Article } from "schema-dts";
import { describe, expect, it } from "vitest";

import BlogPostPage from "@/app/[locale]/(landing)/blog/[slug]/page";
import { getAllBlogSlugs } from "@/lib/blog";
import { getSitemapEntries, SITEMAP_IDS } from "@/lib/sitemapData";

type BlogPostElement = ReactElement<{ structuredData: Article }>;

async function articleDateModified(slug: string): Promise<string> {
  const page = (await BlogPostPage({
    params: Promise.resolve({ slug }),
  })) as BlogPostElement;
  return String(page.props.structuredData.dateModified);
}

describe("blog modification dates", () => {
  it("lists each post in the sitemap at its Article dateModified", async () => {
    const lastmods = new Map(
      (await getSitemapEntries(SITEMAP_IDS.BLOG)).map(
        ({ url, lastModified }) => [url, lastModified],
      ),
    );
    const slugs = await getAllBlogSlugs();
    expect(slugs.length).toBeGreaterThan(0);

    for (const slug of slugs) {
      const lastmod = lastmods.get(`https://heygaia.io/blog/${slug}`);
      expect(lastmod, slug).toBeDefined();
      expect(new Date(lastmod as Date).toISOString(), slug).toBe(
        new Date(await articleDateModified(slug)).toISOString(),
      );
    }
  });
});
