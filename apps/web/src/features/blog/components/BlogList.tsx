"use client";

import { useState } from "react";

import type { BlogPostMeta } from "@/lib/blog";

import { BlogCard } from "./BlogCard";
import { BlogFilters } from "./BlogFilters";

// The first row: two featured cards side by side, or three of the rest when none is featured.
const FEATURED_ROW = 2;
const REST_ROW = 3;

interface BlogListProps {
  blogs: BlogPostMeta[];
}

export function BlogList({ blogs }: BlogListProps) {
  const [filteredBlogs, setFilteredBlogs] = useState<BlogPostMeta[] | null>(
    null,
  );
  const filtered = filteredBlogs ?? blogs;

  const featured = filtered.filter((b) => b.featured);
  const rest = filtered.filter((b) => !b.featured);

  return (
    <>
      <BlogFilters blogs={blogs} onFilterChange={setFilteredBlogs} />

      {filtered.length > 0 ? (
        <div className="space-y-6">
          {featured.length > 0 && (
            <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
              {featured.map((blog, index) => (
                <BlogCard
                  key={blog.slug}
                  blog={blog}
                  variant="large"
                  titleAs="h2"
                  priority={index < FEATURED_ROW}
                />
              ))}
            </div>
          )}

          {rest.length > 0 && (
            <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
              {rest.map((blog, index) => (
                <BlogCard
                  key={blog.slug}
                  blog={blog}
                  variant="small"
                  titleAs="h2"
                  priority={featured.length === 0 && index < REST_ROW}
                />
              ))}
            </div>
          )}
        </div>
      ) : (
        <p className="flex h-full items-center justify-center py-12 text-center text-zinc-400">
          No posts found matching your filters.
        </p>
      )}
    </>
  );
}
