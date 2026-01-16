"use client";

import { ScrollShadow } from "@heroui/scroll-shadow";

import CollapsibleListWrapper from "@/components/shared/CollapsibleListWrapper";
import { ArrowUp02Icon, RedditIcon, UserCircle02Icon } from "@/icons";
import type { RedditCommentData } from "@/types/features/redditTypes";

interface RedditCommentCardProps {
  comments?: RedditCommentData[] | null;
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

export default function RedditCommentCard({
  comments,
  backgroundColor = "bg-surface-200",
  maxHeight = "max-h-[500px]",
  isCollapsible = true,
}: RedditCommentCardProps) {
  if (!comments || comments.length === 0) {
    return null;
  }

  const content = (
    <div
      className={`w-full max-w-2xl rounded-3xl ${backgroundColor} p-3 text-foreground`}
    >
      <ScrollShadow className={`${maxHeight} space-y-3`}>
        {comments.map((comment) => (
          <div
            key={comment.id}
            className="rounded-xl border border-surface-300 bg-surface-100/50 p-3 transition-colors hover:border-surface-400"
          >
            <div className="space-y-2">
              {/* Author & Meta */}
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2 text-xs">
                  <UserCircle02Icon className="h-3.5 w-3.5 text-foreground-400" />
                  <span
                    className={`font-medium ${comment.is_submitter ? "text-blue-400" : "text-foreground-300"}`}
                  >
                    u/{comment.author}
                  </span>
                  {comment.is_submitter && (
                    <span className="rounded bg-blue-900/40 px-1.5 py-0.5 text-[10px] font-medium text-blue-400">
                      OP
                    </span>
                  )}
                  <span className="text-foreground-500">•</span>
                  <span className="text-foreground-500">
                    {formatTime(comment.created_utc)}
                  </span>
                </div>

                {/* Score */}
                <div className="flex items-center gap-1 text-xs text-[#FF4500]">
                  <ArrowUp02Icon width={18} height={18} />
                  <span className="font-medium">
                    {formatNumber(comment.score)}
                  </span>
                </div>
              </div>

              {/* Comment Body */}
              <p className="text-sm leading-relaxed text-foreground-200">
                {comment.body}
              </p>

              {/* Permalink */}
              {comment.permalink && (
                <a
                  href={`https://reddit.com${comment.permalink}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-block text-xs text-[#FF4500] transition-colors hover:text-orange-300"
                >
                  View on Reddit →
                </a>
              )}
            </div>
          </div>
        ))}
      </ScrollShadow>
    </div>
  );

  return (
    <CollapsibleListWrapper
      icon={<RedditIcon />}
      count={comments.length}
      label="Comment"
      isCollapsible={isCollapsible}
    >
      {content}
    </CollapsibleListWrapper>
  );
}
