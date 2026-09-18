"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";

import {
  ArrowUp02Icon,
  ArrowUpRight01Icon,
  BubbleChatIcon,
  LinkSquare02Icon,
} from "@icons";
import Link from "next/link";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
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

  // UTC keeps the rendered date identical between SSR and the browser.
  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: date.getFullYear() !== now.getFullYear() ? "numeric" : undefined,
    timeZone: "UTC",
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
      trackEvent(ANALYTICS_EVENTS.REDDIT_POST_VIEWED, {
        subreddit: post.subreddit,
        score: post.score,
        num_comments: post.num_comments,
        has_selftext: Boolean(post.selftext),
        has_external_link: !post.is_self && Boolean(post.url),
      });
      window.open(
        `https://reddit.com${post.permalink}`,
        "_blank",
        "noopener,noreferrer",
      );
    }
  };

  return (
    <div className="group w-full max-w-2xl overflow-hidden rounded-3xl bg-zinc-800 text-white">
      <div className="space-y-3 p-4">
        {/* Header */}
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            {/* Subreddit & Author */}
            <div className="mb-1.5 flex items-center gap-2 text-xs">
              <span className="font-semibold text-orange-500">
                {post.subreddit}
              </span>
              <span className="text-zinc-400">u/{post.author}</span>
              <span className="text-zinc-500">
                {formatTime(post.created_utc)}
              </span>
            </div>

            {/* Title */}
            {post.permalink ? (
              <Link
                href={`https://reddit.com${post.permalink}`}
                target="_blank"
                rel="noopener noreferrer"
                className="block cursor-pointer"
              >
                <h3 className="text-base leading-snug font-semibold text-white transition-colors group-hover:text-orange-500">
                  {post.title}
                </h3>
              </Link>
            ) : (
              <h3 className="text-base leading-snug font-semibold text-white">
                {post.title}
              </h3>
            )}
          </div>

          {/* Flair if available */}
          {post.link_flair_text && (
            <Chip
              size="sm"
              variant="flat"
              color="primary"
              className="text-xs text-blue-400"
            >
              {post.link_flair_text}
            </Chip>
          )}
        </div>

        {/* Content Preview */}
        {post.selftext && (
          <p className="line-clamp-3 text-sm leading-relaxed text-zinc-300">
            {post.selftext}
          </p>
        )}

        {/* Link Preview */}
        {!post.is_self && post.url && (
          <Link
            href={post.url}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1.5 text-xs text-blue-400 hover:text-blue-400"
          >
            <LinkSquare02Icon className="h-3 w-3" />
            <span className="truncate">{post.url}</span>
          </Link>
        )}

        {/* Footer Stats */}
        <div className="flex items-center gap-4 pt-2">
          {/* Upvotes */}
          <div className="flex items-center gap-1.5 text-sm">
            <ArrowUp02Icon height={18} width={18} className="text-orange-500" />
            <span className="font-medium text-orange-500 tabular-nums">
              {formatNumber(post.score)}
            </span>
            {post.upvote_ratio && (
              <span className="text-xs text-zinc-500 tabular-nums">
                ({Math.round(post.upvote_ratio * 100)}%)
              </span>
            )}
          </div>

          {/* Comments */}
          <div className="flex items-center gap-1.5 text-sm text-zinc-400">
            <BubbleChatIcon className="h-4 w-4" />
            <span className="tabular-nums">
              {formatNumber(post.num_comments)}
            </span>
          </div>

          {/* Open Link */}
          <Button
            variant="light"
            size="sm"
            onPress={handleOpenPost}
            endContent={<ArrowUpRight01Icon className="h-3.5 w-3.5" />}
            className="ml-auto text-xs text-zinc-400"
          >
            View on Reddit
          </Button>
        </div>
      </div>
    </div>
  );
}
