import {
  getAllFeatureEntries,
  getFeatureEntry,
  getFeatureSlugs,
} from "@/lib/feature-data";
import type { BlogPost } from "./blog.types";

export type { Author, BlogPost, BlogPostMeta } from "./blog.types";

// Posts are generated from content/blog/*.mdx into public/data/blog/*.json by
// scripts/extract-blog-data.mjs and loaded via the feature-data loader (fs at
// build, the Cloudflare ASSETS binding at runtime) — never fs at request time,
// which would fail on Cloudflare Workers.
const FEATURE = "blog";

/**
 * Get all blog post slugs.
 */
export async function getAllBlogSlugs(): Promise<string[]> {
  return getFeatureSlugs(FEATURE);
}

/**
 * Get a single blog post by slug.
 */
export async function getBlogPost(slug: string): Promise<BlogPost | null> {
  return (await getFeatureEntry<BlogPost>(FEATURE, slug)) ?? null;
}

/**
 * Get all blog posts sorted by date (newest first), featured first.
 */
export async function getAllBlogPosts(
  includeContent: boolean = false,
): Promise<BlogPost[]> {
  const posts = await getAllFeatureEntries<BlogPost>(FEATURE);

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
