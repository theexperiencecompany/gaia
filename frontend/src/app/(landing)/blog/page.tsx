import type { Metadata } from "next";

import { BlogList } from "@/features/blog/components/BlogList";
import { getAllBlogPosts } from "@/lib/blog";
import { generatePageMetadata } from "@/lib/seo";

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

    return (
      <div className="flex min-h-screen w-screen justify-center py-28">
        <div className="w-full max-w-(--breakpoint-lg) space-y-4">
          <h1>Blog</h1>
          <BlogList blogs={blogs} />
        </div>
      </div>
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
