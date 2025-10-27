import Image from "next/image";
import Link from "next/link";

import { type Author } from "@/types";

import { AuthorTooltip } from "./AuthorTooltip";

export interface Blog {
  slug: string;
  title: string;
  image: string;
  category: string;
  date: string;
  authors: Author[];
}

interface BlogCardProps {
  blog: Blog;
  variant?: "large" | "small";
}

export function BlogCard({ blog, variant = "large" }: BlogCardProps) {
  const isLarge = variant === "large";

  return (
    <Link href={`/blog/${blog.slug}`} className="block">
      <div
        className={`group h-full overflow-hidden rounded-xl bg-zinc-950 p-6 outline-1 outline-zinc-800 transition-all hover:bg-zinc-900 ${isLarge ? "p-7" : "p-4"} `}
      >
        <div className="relative mb-6 aspect-video">
          <Image
            src={blog.image}
            alt={blog.title}
            fill
            className="rounded-xl object-cover"
          />
        </div>
        <div className={`${isLarge ? "space-y-3" : "space-y-2"}`}>
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

          <div className="flex items-center gap-2">
            <span className="text-xs text-foreground-500 group-hover:text-foreground">
              {blog.category}
            </span>
          </div>
          <h3
            className={`font-medium text-white transition-colors ${
              isLarge ? "text-medium" : "line-clamp-2 text-sm"
            }`}
          >
            {blog.title}
          </h3>
        </div>
      </div>
    </Link>
  );
}
