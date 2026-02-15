import type { Metadata } from "next";

import JsonLd from "@/components/seo/JsonLd";
import { BlogList } from "@/features/blog/components/BlogList";
import { getAllBlogPosts } from "@/lib/blog";
import {
  generateBreadcrumbSchema,
  generateItemListSchema,
  generatePageMetadata,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";

export const metadata: Metadata = generatePageMetadata({
  title: "Blog",
  description:
    "Read the latest updates, insights, and stories from the GAIA team. Learn about AI, productivity, open-source development, and our journey building the future of personal AI assistants.",
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
    const blogs = await getAllBlogPosts(false);

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
        description: blog.content.slice(0, 160),
      })),
      "BlogPosting",
    );

    return (
      <>
        <JsonLd data={[webPageSchema, breadcrumbSchema, itemListSchema]} />
        <div className="flex min-h-screen w-screen justify-center py-28">
          <div className="w-full max-w-(--breakpoint-lg) space-y-4">
            <h1 className="font-serif text-6xl">Blog</h1>
            <BlogList blogs={blogs} />
          </div>
        </div>
      </>
    );
  } catch (error) {
    return (
      <div className="flex min-h-screen w-screen justify-center px-6 pt-28">
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
