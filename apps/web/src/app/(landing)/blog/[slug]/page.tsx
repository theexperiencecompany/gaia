import type { Metadata } from "next";
import { cache } from "react";

import BlogPostClient from "@/app/(landing)/blog/client";
import { getAllBlogPosts, getAllBlogSlugs, getBlogPost } from "@/lib/blog";
import {
  generateArticleSchema,
  generateBreadcrumbSchema,
  siteConfig,
} from "@/lib/seo";
import { generateBlogMetadata } from "@/utils/seoUtils";

interface PageProps {
  params: Promise<{ slug: string }>;
}

export const revalidate = 3600;
export const dynamicParams = true;

const getCachedBlogPost = cache(async (slug: string) => {
  return getBlogPost(slug);
});

export async function generateStaticParams() {
  const slugs = await getAllBlogSlugs();
  return slugs.map((slug) => ({
    slug,
  }));
}

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const { slug } = await params;

  try {
    const blog = await getCachedBlogPost(slug);
    if (!blog) {
      return {
        title: "Blog Post Not Found",
        description: "The requested blog post could not be found.",
      };
    }

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
    const blog = await getCachedBlogPost(slug);

    if (!blog) {
      return (
        <div className="flex h-screen items-center justify-center text-medium font-medium text-foreground-500">
          Blog post not found.
        </div>
      );
    }

    // Get suggested posts (excluding current post)
    const allBlogs = await getAllBlogPosts(false);
    const suggestedPosts = allBlogs
      .filter((post) => post.slug !== slug)
      .slice(0, 3);

    // Generate structured data for SEO
    const articleSchema = generateArticleSchema(
      blog.title,
      blog.content.slice(0, 160),
      `${siteConfig.url}/blog/${slug}`,
      blog.image,
      blog.date,
      blog.date,
      blog.authors.map((author) => ({
        name: author.name,
        url: author.twitter,
      })),
      blog.category,
    );
    const breadcrumbSchema = generateBreadcrumbSchema([
      { name: "Home", url: siteConfig.url },
      { name: "Blog", url: `${siteConfig.url}/blog` },
      { name: blog.category, url: `${siteConfig.url}/blog` },
      { name: blog.title, url: `${siteConfig.url}/blog/${slug}` },
    ]);

    return (
      <BlogPostClient
        blog={blog}
        suggestedPosts={suggestedPosts}
        structuredData={articleSchema}
        breadcrumbSchema={breadcrumbSchema}
      />
    );
  } catch (error) {
    return (
      <div>
        Error fetching blog post:{" "}
        {error instanceof Error ? error.message : "Unknown error"}
      </div>
    );
  }
}
