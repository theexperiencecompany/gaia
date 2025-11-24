"use client";

import { ScrollShadow } from "@heroui/scroll-shadow";
import Link from "next/link";

import { RedditIcon } from "@/components";
import CollapsibleListWrapper from "@/components/shared/CollapsibleListWrapper";
import { ArrowUp02Icon, BubbleChatIcon } from "@/icons";
import type { RedditSearchData } from "@/types/features/redditTypes";

interface RedditSearchCardProps {
  posts?: RedditSearchData[] | null;
  backgroundColor?: string;
  maxHeight?: string;
  isCollapsible?: boolean;
}

// Format timestamp to relative time
function formatTime(timestamp: number): string {
  const date = new Date(timestamp * 1000);
  const now = new Date();
  const diffInSeconds = (now.getTime() - date.getTime()) / 1000;

  if (diffInSeconds < 3600) return `${Math.floor(diffInSeconds / 60)}m ago`;
  if (diffInSeconds < 86400) return `${Math.floor(diffInSeconds / 3600)}h ago`;
  if (diffInSeconds < 604800)
    return `${Math.floor(diffInSeconds / 86400)}d ago`;

  return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

// Format number for display
function formatNumber(num: number): string {
  if (num >= 1000) {
    return `${(num / 1000).toFixed(1)}k`;
  }
  return num.toString();
}

export default function RedditSearchCard({
  posts,
  backgroundColor = "bg-zinc-800",
  maxHeight = "max-h-[400px]",
  isCollapsible = true,
}: RedditSearchCardProps) {
  if (!posts || posts.length === 0) return null;

  const content = (
    <div
      className={`w-full max-w-2xl rounded-3xl ${backgroundColor} p-3 text-white`}
    >
      <ScrollShadow className={`${maxHeight} divide-y divide-gray-700`}>
        {posts.map((post, index) => (
          <div
            className="group w-full cursor-pointer p-3 transition-colors hover:bg-zinc-700"
            key={index}
          >
            <Link
              href={`https://reddit.com${post?.permalink}`}
              key={post.id}
              target="_blank"
            >
              <div className="space-y-2">
                {/* Header */}
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <div className="mb-1 flex items-center gap-1.5 text-xs">
                      <span className="font-semibold text-[#FF4500]">
                        {post.subreddit}
                      </span>
                      <span className="text-gray-500">•</span>
                      <span className="text-gray-500">u/{post.author}</span>
                      <span className="text-gray-500">•</span>
                      <span className="text-gray-500">
                        {formatTime(post.created_utc)}
                      </span>
                    </div>
                    <h4 className="line-clamp-2 text-sm leading-snug font-medium text-white group-hover:text-[#FF4500]">
                      {post.title}
                    </h4>
                  </div>
                </div>

                {/* Content preview */}
                {post.selftext && (
                  <p className="line-clamp-2 text-xs leading-relaxed text-gray-400">
                    {post.selftext}
                  </p>
                )}

                {/* Stats */}
                <div className="flex items-center gap-3 text-xs">
                  <div className="flex items-center gap-1 text-[#FF4500]">
                    <ArrowUp02Icon width={18} height={18} />
                    <span className="font-medium">
                      {formatNumber(post.score)}
                    </span>
                  </div>
                  <div className="flex items-center gap-1 text-gray-400">
                    <BubbleChatIcon className="h-3.5 w-3.5" />
                    <span>{formatNumber(post.num_comments)}</span>
                  </div>
                </div>
              </div>
            </Link>
          </div>
        ))}
      </ScrollShadow>
    </div>
  );

  return (
    <CollapsibleListWrapper
      icon={<RedditIcon color="#FF4500" />}
      count={posts.length}
      label="Reddit Post"
      isCollapsible={isCollapsible}
    >
      {content}
    </CollapsibleListWrapper>
  );
}
