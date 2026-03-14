import type { Metadata } from "next";
import { notFound } from "next/navigation";

import BlogPostClient from "@/app/[locale]/(landing)/blog/client";
import type { BlogPostMeta } from "@/lib/blog";
import { getAllBlogPosts, getAllBlogSlugs, getBlogPost } from "@/lib/blog";
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
export const dynamicParams = true;

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

  // Get suggested posts (excluding current post), stripping content before
  // crossing the RSC→client boundary — BlogCard only needs metadata fields.
  const suggestedPosts: BlogPostMeta[] = allBlogs
    .filter((post) => post.slug !== slug)
    .slice(0, 3)
    .map(({ content: _content, ...meta }) => meta);

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
}
