import { Chip } from "@heroui/chip";
import Image from "next/image";
import Link from "next/link";

import type { BlogPost } from "@/lib/blog";

import { AuthorTooltip } from "./AuthorTooltip";

interface BlogCardProps {
  blog: BlogPost;
  variant?: "large" | "small";
}

export function BlogCard({ blog, variant = "large" }: BlogCardProps) {
  const isLarge = variant === "large";

  return (
    <Link href={`/blog/${blog.slug}`} className="block">
      <div
        className={`group flex h-full flex-col overflow-hidden rounded-2xl bg-zinc-900/70 p-6 transition-all hover:bg-zinc-900 ${isLarge ? "p-1" : "p-0"} `}
      >
        {blog.image && (
          <div className="relative mb-6 aspect-video">
            <Image
              src={blog.image}
              alt={blog.title}
              fill
              className="rounded-2xl object-cover"
            />
            {blog.featured && (
              <Chip
                variant="flat"
                color="primary"
                size="sm"
                className="absolute top-3 right-3 text-primary"
              >
                Featured
              </Chip>
            )}
          </div>
        )}
        <div
          className={`${isLarge ? "space-y-3" : "space-y-2"} flex flex-1 flex-col justify-end`}
        >
          <div className="flex items-center -space-x-2">
            {(isLarge ? blog.authors : blog.authors.slice(0, 3)).map(
              (author) => (
                <AuthorTooltip
                  key={author.name}
                  author={author}
                  avatarClassName={
                    isLarge
                      ? "h-8 w-8 cursor-help border-2 border-zinc-700"
                      : "h-6 w-6 cursor-help border-2 border-zinc-700"
                  }
                />
              ),
            )}
            {!isLarge && blog.authors.length > 3 && (
              <div className="flex h-6 w-6 items-center justify-center rounded-full border-2 border-zinc-700 bg-zinc-700 text-xs text-zinc-300">
                +{blog.authors.length - 3}
              </div>
            )}
          </div>

          <div className="mb-1 flex items-center gap-3">
            <span className="text-xs text-foreground-500 group-hover:text-foreground">
              {blog.category}
            </span>
            <span className="text-xs text-foreground-300 group-hover:text-foreground-500">
              {new Date(blog.date).toLocaleDateString("en-US", {
                month: "short",
                day: "numeric",
                year: "numeric",
              })}
            </span>
          </div>
          <h3
            className={`font-medium text-white transition-colors ${
              isLarge ? "text-lg" : "line-clamp-2 text-sm"
            }`}
          >
            {blog.title}
          </h3>
        </div>
      </div>
    </Link>
  );
}
