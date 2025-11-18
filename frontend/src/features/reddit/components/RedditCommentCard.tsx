"use client";

import { ScrollShadow } from "@heroui/scroll-shadow";
import { ArrowBigUp, User } from "lucide-react";

import CollapsibleListWrapper from "@/components/shared/CollapsibleListWrapper";
import { RedditCommentData } from "@/types/features/redditTypes";

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

// Reddit icon component
const RedditIcon = ({ className = "h-5 w-5" }: { className?: string }) => (
  <svg
    viewBox="0 0 24 24"
    fill="currentColor"
    className={className}
    xmlns="http://www.w3.org/2000/svg"
  >
    <path d="M12 0A12 12 0 0 0 0 12a12 12 0 0 0 12 12 12 12 0 0 0 12-12A12 12 0 0 0 12 0zm5.01 4.744c.688 0 1.25.561 1.25 1.249a1.25 1.25 0 0 1-2.498.056l-2.597-.547-.8 3.747c1.824.07 3.48.632 4.674 1.488.308-.309.73-.491 1.207-.491.968 0 1.754.786 1.754 1.754 0 .716-.435 1.333-1.01 1.614a3.111 3.111 0 0 1 .042.52c0 2.694-3.13 4.87-7.004 4.87-3.874 0-7.004-2.176-7.004-4.87 0-.183.015-.366.043-.534A1.748 1.748 0 0 1 4.028 12c0-.968.786-1.754 1.754-1.754.463 0 .898.196 1.207.49 1.207-.883 2.878-1.43 4.744-1.487l.885-4.182a.342.342 0 0 1 .14-.197.35.35 0 0 1 .238-.042l2.906.617a1.214 1.214 0 0 1 1.108-.701zM9.25 12C8.561 12 8 12.562 8 13.25c0 .687.561 1.248 1.25 1.248.687 0 1.248-.561 1.248-1.249 0-.688-.561-1.249-1.249-1.249zm5.5 0c-.687 0-1.248.561-1.248 1.25 0 .687.561 1.248 1.249 1.248.688 0 1.249-.561 1.249-1.249 0-.687-.562-1.249-1.25-1.249zm-5.466 3.99a.327.327 0 0 0-.231.094.33.33 0 0 0 0 .463c.842.842 2.484.913 2.961.913.477 0 2.105-.056 2.961-.913a.361.361 0 0 0 .029-.463.33.33 0 0 0-.464 0c-.547.533-1.684.73-2.512.73-.828 0-1.979-.196-2.512-.73a.326.326 0 0 0-.232-.095z" />
  </svg>
);

export default function RedditCommentCard({
  comments,
  backgroundColor = "bg-zinc-800",
  maxHeight = "max-h-[500px]",
  isCollapsible = true,
}: RedditCommentCardProps) {
  if (!comments || comments.length === 0) {
    return null;
  }

  const content = (
    <div
      className={`w-full max-w-2xl rounded-3xl ${backgroundColor} p-3 text-white`}
    >
      <ScrollShadow className={`${maxHeight} space-y-3`}>
        {comments.map((comment) => (
          <div
            key={comment.id}
            className="rounded-xl border border-zinc-700 bg-zinc-900/50 p-3 transition-colors hover:border-zinc-600"
          >
            <div className="space-y-2">
              {/* Author & Meta */}
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2 text-xs">
                  <User className="h-3.5 w-3.5 text-gray-400" />
                  <span
                    className={`font-medium ${comment.is_submitter ? "text-blue-400" : "text-gray-300"}`}
                  >
                    u/{comment.author}
                  </span>
                  {comment.is_submitter && (
                    <span className="rounded bg-blue-900/40 px-1.5 py-0.5 text-[10px] font-medium text-blue-400">
                      OP
                    </span>
                  )}
                  <span className="text-gray-500">•</span>
                  <span className="text-gray-500">
                    {formatTime(comment.created_utc)}
                  </span>
                </div>

                {/* Score */}
                <div className="flex items-center gap-1 text-xs text-[#FF4500]">
                  <ArrowBigUp width={18} height={18} />
                  <span className="font-medium">
                    {formatNumber(comment.score)}
                  </span>
                </div>
              </div>

              {/* Comment Body */}
              <p className="text-sm leading-relaxed text-gray-200">
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
