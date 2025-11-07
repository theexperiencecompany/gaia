import type { Metadata } from "next";

import BlogPostClient from "@/app/(landing)/blog/client";
import { blogApi } from "@/features/blog/api/blogApi";
import {
  generateBlogMetadata,
  generateBlogStructuredData,
} from "@/utils/seoUtils";

interface PageProps {
  params: Promise<{ slug: string }>;
}

export const revalidate = 3600; // Revalidate every hour

export async function generateStaticParams() {
  try {
    const blogs = await blogApi.getBlogs(false);
    return blogs.map((blog) => ({
      slug: blog.slug,
    }));
  } catch (error) {
    console.error("Error generating static params for blogs:", error);
    return [];
  }
}

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const { slug } = await params;

  try {
    const blog = await blogApi.getBlog(slug);
    return generateBlogMetadata(blog);
  } catch {
    return {
      title: "Blog Post Not Found",
      description: "The requested blog post could not be found.",
    };
  }
}

export default async function BlogPostPage({ params }: PageProps) {
  const { slug } = await params;

  try {
    const blog = await blogApi.getBlog(slug);

    if (!blog) {
      return (
        <div className="flex h-screen items-center justify-center text-medium font-medium text-foreground-500">
          Blog post not found.
        </div>
      );
    }

    const structuredData = generateBlogStructuredData(blog);

    return <BlogPostClient blog={blog} structuredData={structuredData} />;
  } catch (error) {
    return (
      <div>
        Error fetching blog post:{" "}
        {error instanceof Error ? error.message : "Unknown error"}
      </div>
    );
  }
}
