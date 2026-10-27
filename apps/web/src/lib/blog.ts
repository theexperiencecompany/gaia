import {
  getAllFeatureEntries,
  getFeatureEntry,
  getFeatureSlugs,
} from "@/lib/feature-data";
import type { BlogContentPost } from "./blog.types";

export type { BlogContentPost, BlogPostMeta } from "./blog.types";

// Posts are generated from content/blog/*.mdx into public/data/blog/*.json
// (scripts/extract-blog-data.mjs) and loaded via feature-data (fs at build,
// the Cloudflare ASSETS binding at runtime — never fs at request time, which fails on Workers).
const FEATURE = "blog";

/** When a post last changed: its revision date, else its publish date. The sitemap lastmod, Article dateModified and og:modified_time all read this. */
export function blogLastModified(
  post: Pick<BlogContentPost, "date" | "updated">,
): string {
  return post.updated ?? post.date;
}

/**
 * Get all blog post slugs.
 */
export async function getAllBlogSlugs(): Promise<string[]> {
  return getFeatureSlugs(FEATURE);
}

/**
 * Get a single blog post by slug.
 */
export async function getBlogPost(
  slug: string,
): Promise<BlogContentPost | null> {
  return (await getFeatureEntry<BlogContentPost>(FEATURE, slug)) ?? null;
}

/**
 * Get all blog posts sorted by date (newest first), featured first.
 */
export async function getAllBlogPosts(
  includeContent: boolean = false,
): Promise<BlogContentPost[]> {
  const posts = await getAllFeatureEntries<BlogContentPost>(FEATURE);

  return posts
    .map((post) => (includeContent ? post : { ...post, content: "" }))
    .toSorted((a, b) => {
      // Featured posts come first
      if (a.featured && !b.featured) return -1;
      if (!a.featured && b.featured) return 1;

      // Then newest first
      return new Date(b.date).getTime() - new Date(a.date).getTime();
    });
}
