import type { Metadata } from "next";

import JsonLd from "@/components/seo/JsonLd";
import { BlogList } from "@/features/blog/components/BlogList";
import type { BlogPostMeta } from "@/lib/blog";
import { getAllBlogPosts } from "@/lib/blog";
import {
  generateBreadcrumbSchema,
  generateItemListSchema,
  generatePageMetadata,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";

export const metadata: Metadata = generatePageMetadata({
  title: "GAIA Blog: Product Updates and Engineering Notes",
  description:
    "Product updates, guides, and engineering notes from the team building GAIA, covering AI assistants, productivity, and how the product works inside.",
  path: "/blog",
  keywords: [
    "GAIA Blog",
    "AI News",
    "Product Updates",
    "Tech Blog",
    "Open Source",
    "AI Assistant",
    "Productivity Tips",
  ],
});

export default async function BlogPage() {
  try {
    // Load content so the ItemList schema can derive per-post descriptions;
    // it is stripped again before crossing the RSC→client boundary below.
    const blogs = await getAllBlogPosts(true);

    const webPageSchema = generateWebPageSchema(
      "Blog",
      "Read the latest updates, insights, and stories from the GAIA team.",
      `${siteConfig.url}/blog`,
      [
        { name: "Home", url: siteConfig.url },
        { name: "Blog", url: `${siteConfig.url}/blog` },
      ],
    );
    const breadcrumbSchema = generateBreadcrumbSchema([
      { name: "Home", url: siteConfig.url },
      { name: "Blog", url: `${siteConfig.url}/blog` },
    ]);
    const itemListSchema = generateItemListSchema(
      blogs.map((blog) => ({
        name: blog.title,
        url: `${siteConfig.url}/blog/${blog.slug}`,
      })),
    );

    // Strip content before crossing the RSC→client boundary — BlogList only
    // needs metadata fields (slug, title, date, authors, category, image, featured).
    const blogsMeta: BlogPostMeta[] = blogs.map(
      ({ content: _content, ...meta }) => meta,
    );

    return (
      <>
        <JsonLd data={[webPageSchema, breadcrumbSchema, itemListSchema]} />
        <div className="flex min-h-screen w-full justify-center px-4 py-28 sm:px-6 lg:px-8">
          <div className="w-full max-w-(--breakpoint-lg) space-y-2">
            <h1 className="font-serif text-4xl sm:text-6xl">Blog</h1>
            <p className="max-w-2xl text-base leading-relaxed text-zinc-400">
              The GAIA blog is where the team writes about what we build and
              why. Posts cover product releases, engineering decisions, and
              practical guides to AI assistants, automation, email, calendars,
              and tasks. Some entries announce a new feature; others explain how
              it works, the tradeoffs behind it, and what it changes in a
              working day. Use the category filters to narrow the list by topic,
              or start with the featured posts if you are new. Every post is
              dated, so you can tell what is current. The archive goes back to
              early 2025, so older posts also show how the product and its
              thinking have changed. Read it to follow the product&apos;s
              direction, not just its changelog.
            </p>
            <BlogList blogs={blogsMeta} />
          </div>
        </div>
      </>
    );
  } catch (error) {
    return (
      <div className="flex min-h-screen w-full justify-center px-4 pt-28 sm:px-6 lg:px-8">
        <div className="w-full max-w-(--breakpoint-lg)">
          <div className="flex flex-col items-center justify-center py-20">
            <span className="text-danger">Error loading blog posts</span>
            <span className="mt-2 text-sm text-foreground-500">
              {error instanceof Error ? error.message : "Failed to fetch blogs"}
            </span>
          </div>
        </div>
      </div>
    );
  }
}
