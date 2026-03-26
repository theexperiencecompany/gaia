"use client";

import { BreadcrumbItem, Breadcrumbs } from "@heroui/react";
import Image from "next/image";
import type { Article, BreadcrumbList, WithContext } from "schema-dts";

import JsonLd from "@/components/seo/JsonLd";
import { BlogCard } from "@/features/blog/components/BlogCard";
import BlogMetadata from "@/features/blog/components/BlogMetadata";
import MarkdownWrapper from "@/features/blog/components/MarkdownWrapper";
import TableOfContents from "@/features/blog/components/TableOfContents";
import { parseHeadings } from "@/features/blog/utils/parseHeadings";
import SearchedImageDialog from "@/features/chat/components/bubbles/bot/SearchedImageDialog";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import type { BlogPost } from "@/lib/blog";

interface BlogPostClientProps {
  blog: BlogPost;
  suggestedPosts: BlogPost[];
  structuredData: WithContext<Article>;
  breadcrumbSchema: WithContext<BreadcrumbList>;
}

export default function BlogPostClient({
  blog,
  suggestedPosts,
  structuredData,
  breadcrumbSchema,
}: BlogPostClientProps) {
  if (!blog) {
    return (
      <div className="flex h-screen items-center justify-center text-medium font-medium text-foreground-500">
        Blog post not found.
      </div>
    );
  }

  const headings = parseHeadings(blog.content);

  return (
    <>
      <JsonLd data={[structuredData, breadcrumbSchema]} />
      <SearchedImageDialog />
      <div className="min-h-screen w-full pt-28">
        {/* Centered header */}
        <div className="mx-auto mb-10 flex max-w-3xl flex-col items-center space-y-10 px-5">
          <div className="flex w-full justify-center text-foreground-400">
            <Breadcrumbs>
              <BreadcrumbItem href="/blog">Blog</BreadcrumbItem>
              <BreadcrumbItem>{blog.category}</BreadcrumbItem>
            </Breadcrumbs>
          </div>

          {blog.image && (
            <Image
              src={blog.image}
              alt={blog.title}
              width={1920}
              height={1080}
              className="w-full bg-zinc-900 object-cover"
            />
          )}

          <h1 className="text-center text-4xl font-medium tracking-tight sm:text-5xl">
            {blog.title}
          </h1>

          <BlogMetadata authors={blog.authors} date={blog.date} />
        </div>

        {/* Content + TOC: flex layout so sticky works in normal flow */}
        <div className="mx-auto flex max-w-5xl justify-center gap-16 px-5">
          <article className="w-full max-w-3xl">
            <MarkdownWrapper content={blog.content} />
            <BlogMetadata
              authors={blog.authors}
              date={blog.date}
              className="my-10 border-t border-zinc-800 pt-10"
            />
          </article>

          {headings.length > 0 && (
            <aside className="hidden shrink-0 xl:block">
              <TableOfContents headings={headings} />
            </aside>
          )}
        </div>

        {/* Suggested Posts Section */}
        {suggestedPosts.length > 0 && (
          <div className="mx-auto max-w-5xl px-5 my-16">
            <h2 className="mb-8 text-2xl font-medium">Suggested Posts</h2>
            <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
              {suggestedPosts.map((post) => (
                <BlogCard key={post.slug} blog={post} variant="small" />
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Final Section */}
      <FinalSection />
    </>
  );
}
