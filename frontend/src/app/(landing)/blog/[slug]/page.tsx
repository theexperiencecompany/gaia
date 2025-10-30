import type { Metadata } from "next";
import Image from "next/image";

import { blogApi } from "@/features/blog/api/blogApi";
import BlogMetadata from "@/features/blog/components/BlogMetadata";
import MarkdownWrapper from "@/features/blog/components/MarkdownWrapper";
import {
  generateBlogMetadata,
  generateBlogStructuredData,
} from "@/utils/seoUtils";
import { BreadcrumbItem, Breadcrumbs } from "@heroui/react";

interface PageProps {
  params: Promise<{ slug: string }>;
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

    return (
      <>
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(structuredData) }}
        />
        <div className="flex h-fit min-h-screen w-screen justify-center overflow-y-auto pt-28">
          <div className="mx-auto w-full px-5 sm:p-0">
            <div className="mb-8 flex flex-col items-center">
              <div className="mb-5 flex w-full justify-center text-foreground-400">
                <Breadcrumbs>
                  <BreadcrumbItem href="/blog">Blog</BreadcrumbItem>
                  <BreadcrumbItem>{blog.category}</BreadcrumbItem>
                </Breadcrumbs>
              </div>

              <h1 className="text-center text-4xl font-medium tracking-tight sm:text-5xl">
                {blog.title}
              </h1>

              <div className="flex h-fit max-w-4xl items-center justify-center py-10">
                {blog.image && (
                  <Image
                    src={blog.image}
                    alt={blog.title}
                    width={1920}
                    height={1080}
                    className="object-cover sm:max-w-5xl"
                  />
                )}
              </div>

              <BlogMetadata
                authors={blog.author_details}
                date={blog.date}
                className="mb-10"
              />

              <div className="prose prose-lg dark:prose-invert max-w-2xl text-foreground-600">
                <MarkdownWrapper content={blog.content.toString()} />
              </div>

              <BlogMetadata
                authors={blog.author_details}
                date={blog.date}
                className="my-10 w-full max-w-3xl border-t-1 border-gray-700 py-10"
              />
            </div>
          </div>
        </div>
      </>
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
