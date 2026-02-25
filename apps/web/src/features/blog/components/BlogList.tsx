"use client";

import { useState } from "react";

import type { BlogPost } from "@/lib/blog";

import { BlogCard } from "./BlogCard";
import { BlogFilters } from "./BlogFilters";

interface BlogListProps {
  blogs: BlogPost[];
}

export function BlogList({ blogs }: BlogListProps) {
  const [filtered, setFilteredBlogs] = useState(blogs);

  const featured = filtered.filter((b) => b.featured);
  const rest = filtered.filter((b) => !b.featured);

  return (
    <>
      <BlogFilters blogs={blogs} onFilterChange={setFilteredBlogs} />

      {filtered.length > 0 ? (
        <div className="space-y-6">
          {featured.length > 0 && (
            <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
              {featured.map((blog) => (
                <BlogCard key={blog.slug} blog={blog} variant="large" />
              ))}
            </div>
          )}

          {rest.length > 0 && (
            <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
              {rest.map((blog) => (
                <BlogCard key={blog.slug} blog={blog} variant="small" />
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
