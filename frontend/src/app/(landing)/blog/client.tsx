"use client";

import { BreadcrumbItem, Breadcrumbs } from "@heroui/react";
import Image from "next/image";
import type { Article, WithContext } from "schema-dts";

import JsonLd from "@/components/seo/JsonLd";
import BlogMetadata from "@/features/blog/components/BlogMetadata";
import MarkdownWrapper from "@/features/blog/components/MarkdownWrapper";
import SearchedImageDialog from "@/features/chat/components/bubbles/bot/SearchedImageDialog";
import type { BlogPost } from "@/lib/blog";

interface BlogPostClientProps {
  blog: BlogPost;
  structuredData: WithContext<Article>;
}

export default function BlogPostClient({
  blog,
  structuredData,
}: BlogPostClientProps) {
  if (!blog) {
    return (
      <div className="flex h-screen items-center justify-center text-medium font-medium text-foreground-500">
        Blog post not found.
      </div>
    );
  }

  return (
    <>
      <JsonLd data={structuredData} />
      <SearchedImageDialog />
      <div className="flex h-fit min-h-screen w-screen justify-center overflow-y-auto pt-28">
        <div className="mx-auto w-full px-5 sm:p-0">
          <div className="mb-8 flex flex-col items-center space-y-10">
            <div className="flex w-full justify-center text-foreground-400">
              <Breadcrumbs>
                <BreadcrumbItem href="/blog">Blog</BreadcrumbItem>
                <BreadcrumbItem>{blog.category}</BreadcrumbItem>
              </Breadcrumbs>
            </div>

            <div className="flex h-fit max-w-3xl items-center justify-center">
              {blog.image && (
                <Image
                  src={blog.image}
                  alt={blog.title}
                  width={1920}
                  height={1080}
                  className="bg-zinc-900 object-cover sm:max-w-5xl"
                />
              )}
            </div>

            <h1 className="text-center text-4xl font-medium tracking-tight sm:text-5xl">
              {blog.title}
            </h1>

            <BlogMetadata
              authors={blog.authors}
              date={blog.date}
              className="mb-10"
            />
            <div className="prose prose-lg dark:prose-invert max-w-2xl text-foreground-600">
              <MarkdownWrapper content={blog.content} />
            </div>
            <BlogMetadata
              authors={blog.authors}
              date={blog.date}
              className="my-10 w-full max-w-3xl border-t-1 border-gray-700 py-10"
            />
          </div>
        </div>
      </div>
    </>
  );
}
