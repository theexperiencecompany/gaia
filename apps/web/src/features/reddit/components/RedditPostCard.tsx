"use client";

import { Chip } from "@heroui/chip";

import { ArrowUp02Icon, BubbleChatIcon, LinkSquare02Icon } from "@icons";
import type { RedditPostData } from "@/types/features/redditTypes";

interface RedditPostCardProps {
  post: RedditPostData;
}

// Format timestamp to relative time
function formatTime(timestamp: number): string {
  const date = new Date(timestamp * 1000); // Convert Unix timestamp to ms
  const now = new Date();
  const diffInSeconds = (now.getTime() - date.getTime()) / 1000;

  if (diffInSeconds < 60) return "Just now";
  if (diffInSeconds < 3600)
    return `${Math.floor(diffInSeconds / 60)} minutes ago`;
  if (diffInSeconds < 86400)
    return `${Math.floor(diffInSeconds / 3600)} hours ago`;
  if (diffInSeconds < 604800)
    return `${Math.floor(diffInSeconds / 86400)} days ago`;

  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: date.getFullYear() !== now.getFullYear() ? "numeric" : undefined,
  });
}

// Format number for display (e.g., 1.2k, 3.4k)
function formatNumber(num: number): string {
  if (num >= 1000) {
    return `${(num / 1000).toFixed(1)}k`;
  }
  return num.toString();
}

export default function RedditPostCard({ post }: RedditPostCardProps) {
  const handleOpenPost = () => {
    if (post.permalink) {
      window.open(`https://reddit.com${post.permalink}`, "_blank");
    }
  };

  return (
    <div className="group w-full max-w-2xl overflow-hidden rounded-2xl border border-zinc-700 bg-zinc-800 text-white transition-all hover:border-orange-600/50 hover:shadow-lg hover:shadow-orange-600/10">
      <div className="space-y-3 p-4">
        {/* Header */}
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            {/* Subreddit & Author */}
            <div className="mb-1.5 flex items-center gap-2 text-xs">
              <span className="font-semibold text-[#FF4500]">
                {post.subreddit}
              </span>
              <span className="text-gray-500">•</span>
              <span className="text-gray-400">u/{post.author}</span>
              <span className="text-gray-500">•</span>
              <span className="text-gray-500">
                {formatTime(post.created_utc)}
              </span>
            </div>

            {/* Title */}
            <h3
              className="cursor-pointer text-base leading-snug font-semibold text-white transition-colors group-hover:text-[#FF4500]"
              onClick={handleOpenPost}
            >
              {post.title}
            </h3>
          </div>

          {/* Flair if available */}
          {post.link_flair_text && (
            <Chip
              size="sm"
              variant="flat"
              className="flex-shrink-0 bg-blue-900/30 text-xs text-blue-300"
            >
              {post.link_flair_text}
            </Chip>
          )}
        </div>

        {/* Content Preview */}
        {post.selftext && (
          <p className="line-clamp-3 text-sm leading-relaxed text-gray-300">
            {post.selftext}
          </p>
        )}

        {/* Link Preview */}
        {!post.is_self && post.url && (
          <a
            href={post.url}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1.5 text-xs text-blue-400 hover:text-blue-300"
          >
            <LinkSquare02Icon className="h-3 w-3" />
            <span className="truncate">{post.url}</span>
          </a>
        )}

        {/* Footer Stats */}
        <div className="flex items-center gap-4 pt-2">
          {/* Upvotes */}
          <div className="flex items-center gap-1.5 text-sm">
            <ArrowUp02Icon height={18} width={18} className="text-[#FF4500]" />
            <span className="font-medium text-[#FF4500]">
              {formatNumber(post.score)}
            </span>
            {post.upvote_ratio && (
              <span className="text-xs text-gray-500">
                ({Math.round(post.upvote_ratio * 100)}%)
              </span>
            )}
          </div>

          {/* Comments */}
          <div className="flex items-center gap-1.5 text-sm text-gray-400">
            <BubbleChatIcon className="h-4 w-4" />
            <span>{formatNumber(post.num_comments)}</span>
          </div>

          {/* Open Link */}
          <button
            type="button"
            onClick={handleOpenPost}
            className="ml-auto text-xs text-gray-400 transition-colors hover:text-[#FF4500]"
          >
            View on Reddit →
          </button>
        </div>
      </div>
    </div>
  );
}
