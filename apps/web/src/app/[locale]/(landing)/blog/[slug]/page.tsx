import type { Metadata } from "next";
import { notFound } from "next/navigation";

import BlogPostClient from "@/app/[locale]/(landing)/blog/client";
import type { BlogPostMeta } from "@/lib/blog";
import {
  blogLastModified,
  getAllBlogPosts,
  getAllBlogSlugs,
  getBlogPost,
} from "@/lib/blog";
import { circularNeighbours } from "@/lib/circularNeighbours";
import { prerenderedMarketingParams } from "@/lib/selfhost";
import {
  generateArticleSchema,
  generateBreadcrumbSchema,
  siteConfig,
} from "@/lib/seo";
import { generateBlogMetadata } from "@/utils/seoUtils";

interface PageProps {
  params: Promise<{ readonly slug: string }>;
}

export const revalidate = 3600;

/** The next three posts in listing order, wrapping: every post is suggested by three others, the oldest included. */
const SUGGESTED_POST_OFFSETS = [1, 2, 3] as const;

export const dynamicParams = true;

async function allStaticParams() {
  const slugs = await getAllBlogSlugs();
  return slugs.map((slug) => ({
    slug,
  }));
}

export function generateStaticParams() {
  return prerenderedMarketingParams(allStaticParams);
}

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const { slug } = await params;

  try {
    const blog = await getBlogPost(slug);
    if (!blog) {
      return {
        title: "Blog Post Not Found",
        description: "The requested blog post could not be found.",
      };
    }

    const metadata = generateBlogMetadata(blog);
    return metadata;
  } catch {
    return {
      title: "Blog Post Not Found",
      description: "The requested blog post could not be found.",
    };
  }
}

export default async function BlogPostPage({ params }: PageProps) {
  const { slug } = await params;

  // Fetch blog post and all posts in parallel - they are independent
  const [blog, allBlogs] = await Promise.all([
    getBlogPost(slug),
    getAllBlogPosts(false),
  ]);

  if (!blog) {
    notFound();
  }

  // Content is stripped before the RSC→client boundary: BlogCard only needs metadata.
  const suggestedPosts: BlogPostMeta[] = circularNeighbours(
    allBlogs,
    allBlogs.findIndex((post) => post.slug === slug),
    SUGGESTED_POST_OFFSETS,
  ).map(({ content: _content, ...meta }) => meta);

  // Generate structured data for SEO
  const articleSchema = generateArticleSchema(
    blog.title,
    blog.content.slice(0, 160),
    `${siteConfig.url}/blog/${slug}`,
    blog.image,
    blog.date,
    blogLastModified(blog),
    blog.authors.map((author) => ({
      name: author.name,
      jobTitle: author.role,
      url: author.linkedin,
      sameAs: [author.linkedin, author.twitter, author.github],
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
}
