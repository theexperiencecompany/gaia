import type { Metadata } from "next";

import BlogPostClient from "@/app/(landing)/blog/client";
import { getAllBlogSlugs, getBlogPost } from "@/lib/blog";

interface PageProps {
  params: Promise<{ slug: string }>;
}

export const revalidate = 3600; // Revalidate every hour

export async function generateStaticParams() {
  const slugs = getAllBlogSlugs();
  return slugs.map((slug) => ({
    slug,
  }));
}

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const { slug } = await params;

  try {
    // Read blog post from markdown file
    const blog = getBlogPost(slug);
    if (!blog) {
      return {
        title: "Blog Post Not Found",
        description: "The requested blog post could not be found.",
      };
    }

    // Generate metadata from the blog post
    return {
      title: blog.title,
      description: blog.content.slice(0, 160),
      openGraph: {
        title: blog.title,
        description: blog.content.slice(0, 160),
        images: [blog.image],
        type: "article",
        publishedTime: blog.date,
      },
    };
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
    // Read blog post from markdown file
    const blog = getBlogPost(slug);

    if (!blog) {
      return (
        <div className="flex h-screen items-center justify-center text-medium font-medium text-foreground-500">
          Blog post not found.
        </div>
      );
    }

    // Generate structured data for SEO
    const structuredData = {
      "@context": "https://schema.org" as const,
      "@type": "BlogPosting" as const,
      headline: blog.title,
      image: blog.image,
      datePublished: blog.date,
      author: blog.authors.map((author) => ({
        "@type": "Person" as const,
        name: author.name,
      })),
    };

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
