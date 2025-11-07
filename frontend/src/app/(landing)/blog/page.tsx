import { BlogCard } from "@/features/blog/components/BlogCard";
import { BlogHeader } from "@/features/blog/components/BlogHeader";
import { BlogListItem } from "@/features/blog/components/BlogListItem";
import { getAllBlogPosts } from "@/lib/blog";
import { generatePageMetadata } from "@/lib/seo";
import type { Metadata } from "next";

interface Blog {
  slug: string;
  title: string;
  category: string;
  date: string;
  image: string;
  authors: Array<{
    name: string;
    role: string;
    avatar: string;
    linkedin?: string;
    twitter?: string;
  }>;
}

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

export default async function BlogList() {
  try {
    // Read blogs from markdown files instead of API
    const blogs = getAllBlogPosts(false);
    const displayBlogs: Blog[] = blogs.map((blog) => ({
      slug: blog.slug,
      title: blog.title,
      category: blog.category,
      date: blog.date,
      image: blog.image,
      authors: blog.authors,
    }));

    const latestPosts = displayBlogs.slice(0, 5);
    const remainingPosts = displayBlogs.slice(5);

    return (
      <div className="flex min-h-screen w-screen justify-center pt-28">
        <div className="w-full max-w-(--breakpoint-lg)">
          <BlogHeader />

          {/* Latest Posts Grid */}
          {latestPosts.length > 0 && (
            <div className="mb-12">
              <div className="mb-6 grid gap-6">
                {/* First row - 2 posts */}
                <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
                  {latestPosts.slice(0, 2).map((blog) => (
                    <BlogCard key={blog.slug} blog={blog} variant="large" />
                  ))}
                </div>

                {/* Second row - 3 posts */}
                {latestPosts.length > 2 && (
                  <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
                    {latestPosts.slice(2, 5).map((blog) => (
                      <BlogCard key={blog.slug} blog={blog} variant="small" />
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* More News Section */}
          {remainingPosts.length > 0 && (
            <div className="dark">
              <div className="my-7 space-y-2 px-6">
                <div className="text-sm font-medium text-foreground-300">
                  More News
                </div>
                <div className="h-px w-full bg-foreground-300"></div>
              </div>
              {remainingPosts.map((blog) => (
                <BlogListItem key={blog.slug} blog={blog} />
              ))}
            </div>
          )}

          {displayBlogs.length === 0 && (
            <p className="flex h-full items-center justify-center text-center text-zinc-400">
              No posts available.
            </p>
          )}
        </div>
      </div>
    );
  } catch (error) {
    return (
      <div className="flex min-h-screen w-screen justify-center px-6 pt-28">
        <div className="w-full max-w-(--breakpoint-lg)">
          <BlogHeader />
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
