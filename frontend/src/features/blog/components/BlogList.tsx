"use client";

import { useState } from "react";
import type { BlogPost } from "@/lib/blog";

import { BlogCard } from "./BlogCard";
import { BlogFilters } from "./BlogFilters";
import { BlogListItem } from "./BlogListItem";

interface BlogListProps {
  blogs: BlogPost[];
}

export function BlogList({ blogs }: BlogListProps) {
  const [filtered, setFilteredBlogs] = useState(blogs);

  const moreThan5 = filtered.length > 5;
  const latest = filtered.slice(0, moreThan5 ? 5 : filtered.length);
  const remaining = filtered.slice(moreThan5 ? 5 : filtered.length);

  return (
    <>
      <BlogFilters blogs={blogs} onFilterChange={setFilteredBlogs} />

      {latest.length > 0 && (
        <div className="mb-12">
          <div className="mb-6 grid gap-6">
            <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
              {latest.slice(0, 2).map((blog) => (
                <BlogCard key={blog.slug} blog={blog} variant="large" />
              ))}
            </div>

            {latest.length > 2 && (
              <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
                {latest.slice(2, 5).map((blog) => (
                  <BlogCard key={blog.slug} blog={blog} variant="small" />
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {remaining.length > 0 && (
        <div className="dark">
          <div className="my-7 space-y-2 px-2">
            <div className="text-sm text-foreground-400">More News</div>
            <div className="h-px w-full bg-foreground-100" />
          </div>
          {remaining.map((blog) => (
            <BlogListItem key={blog.slug} blog={blog} />
          ))}
        </div>
      )}

      {filtered.length === 0 && (
        <p className="flex h-full items-center justify-center py-12 text-center text-zinc-400">
          No posts found matching your filters.
        </p>
      )}
    </>
  );
}
