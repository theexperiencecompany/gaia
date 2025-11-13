import Link from "next/link";

import { type BlogPost } from "@/lib/blog";

import { AuthorTooltip } from "./AuthorTooltip";

interface BlogListItemProps {
  blog: BlogPost;
}

export function BlogListItem({ blog }: BlogListItemProps) {
  return (
    <div>
      <Link href={`/blog/${blog.slug}`} className="block">
        <div className="grid grid-cols-[minmax(0,4fr)_minmax(0,1.5fr)_minmax(0,1fr)_minmax(0,0.7fr)] items-center rounded-lg px-3 py-3 transition-all hover:bg-zinc-800">
          <div className="truncate text-sm">{blog.title}</div>
          <div className="text-sm text-foreground-400">{blog.category}</div>
          <div className="text-sm text-foreground-400">{blog.date}</div>
          <div className="flex items-center -space-x-1">
            {blog.authors.map((author) => (
              <AuthorTooltip
                key={author.name}
                author={author}
                avatarClassName="h-6 w-6 cursor-help"
              />
            ))}
          </div>
        </div>
      </Link>
    </div>
  );
}
