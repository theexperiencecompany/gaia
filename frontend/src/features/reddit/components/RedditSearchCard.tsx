"use client";

import { ScrollShadow } from "@heroui/scroll-shadow";
import { MessageCircle, TrendingUp } from "lucide-react";

import CollapsibleListWrapper from "@/components/shared/CollapsibleListWrapper";
import { useAppendToInput } from "@/stores/composerStore";
import { RedditSearchData } from "@/types/features/redditTypes";

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

export default function RedditSearchCard({
  posts,
  backgroundColor = "bg-zinc-800",
  maxHeight = "max-h-[400px]",
  isCollapsible = true,
}: RedditSearchCardProps) {
  const appendToInput = useAppendToInput();

  const handlePostClick = (post: RedditSearchData) => {
    appendToInput(
      `Tell me more about the Reddit post "${post.title}" from r/${post.subreddit.replace("r/", "")}`,
    );
  };

  if (!posts || posts.length === 0) {
    return null;
  }

  const content = (
    <div
      className={`w-full max-w-2xl rounded-3xl ${backgroundColor} p-3 text-white`}
    >
      <ScrollShadow className={`${maxHeight} divide-y divide-gray-700`}>
        {posts.map((post) => (
          <div
            key={post.id}
            className="group cursor-pointer p-3 transition-colors hover:bg-zinc-700"
            onClick={() => handlePostClick(post)}
          >
            <div className="space-y-2">
              {/* Header */}
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0 flex-1">
                  <div className="mb-1 flex items-center gap-1.5 text-xs">
                    <span className="font-semibold text-orange-400">
                      {post.subreddit}
                    </span>
                    <span className="text-gray-500">•</span>
                    <span className="text-gray-500">u/{post.author}</span>
                    <span className="text-gray-500">•</span>
                    <span className="text-gray-500">
                      {formatTime(post.created_utc)}
                    </span>
                  </div>
                  <h4 className="line-clamp-2 text-sm leading-snug font-medium text-white group-hover:text-orange-400">
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
                <div className="flex items-center gap-1 text-orange-400">
                  <TrendingUp className="h-3.5 w-3.5" />
                  <span className="font-medium">
                    {formatNumber(post.score)}
                  </span>
                </div>
                <div className="flex items-center gap-1 text-gray-400">
                  <MessageCircle className="h-3.5 w-3.5" />
                  <span>{formatNumber(post.num_comments)}</span>
                </div>
              </div>
            </div>
          </div>
        ))}
      </ScrollShadow>
    </div>
  );

  return (
    <CollapsibleListWrapper
      icon={<RedditIcon />}
      count={posts.length}
      label="Reddit Post"
      isCollapsible={isCollapsible}
    >
      {content}
    </CollapsibleListWrapper>
  );
}
