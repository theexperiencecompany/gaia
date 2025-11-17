"use client";

import { Chip } from "@heroui/chip";
import { CheckCircleIcon, ExternalLink } from "lucide-react";

import {
  RedditPostCreatedData,
  RedditCommentCreatedData,
} from "@/types/features/redditTypes";

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

interface RedditPostCreatedCardProps {
  data: RedditPostCreatedData;
}

export function RedditPostCreatedCard({ data }: RedditPostCreatedCardProps) {
  const openPost = () => {
    if (data.permalink) {
      window.open(`https://reddit.com${data.permalink}`, "_blank");
    } else if (data.url) {
      window.open(data.url, "_blank");
    }
  };

  return (
    <div className="mx-auto w-full max-w-2xl rounded-2xl border border-orange-700/30 bg-orange-900/20 p-4 text-white">
      {/* Header */}
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <RedditIcon className="text-orange-400" />
          <CheckCircleIcon className="h-5 w-5 text-green-400" />
          <span className="text-sm font-medium text-green-400">
            Post Created Successfully
          </span>
        </div>
        <Chip size="sm" variant="flat" color="success" className="text-xs">
          Just now
        </Chip>
      </div>

      {/* Content */}
      <div className="space-y-2">
        <div className="text-sm font-medium text-orange-400">
          {data.message}
        </div>

        {data.id && (
          <div className="text-xs text-gray-400">
            <span className="text-gray-500">Post ID: </span>
            <span className="font-mono text-gray-300">{data.id}</span>
          </div>
        )}

        {(data.permalink || data.url) && (
          <button
            onClick={openPost}
            className="flex items-center gap-1.5 text-sm text-orange-400 transition-colors hover:text-orange-300"
          >
            <ExternalLink className="h-4 w-4" />
            <span>View on Reddit</span>
          </button>
        )}
      </div>
    </div>
  );
}

interface RedditCommentCreatedCardProps {
  data: RedditCommentCreatedData;
}

export function RedditCommentCreatedCard({
  data,
}: RedditCommentCreatedCardProps) {
  const openComment = () => {
    if (data.permalink) {
      window.open(`https://reddit.com${data.permalink}`, "_blank");
    }
  };

  return (
    <div className="mx-auto w-full max-w-2xl rounded-2xl border border-orange-700/30 bg-orange-900/20 p-4 text-white">
      {/* Header */}
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <RedditIcon className="text-orange-400" />
          <CheckCircleIcon className="h-5 w-5 text-green-400" />
          <span className="text-sm font-medium text-green-400">
            Comment Posted Successfully
          </span>
        </div>
        <Chip size="sm" variant="flat" color="success" className="text-xs">
          Just now
        </Chip>
      </div>

      {/* Content */}
      <div className="space-y-2">
        <div className="text-sm font-medium text-orange-400">
          {data.message}
        </div>

        {data.id && (
          <div className="text-xs text-gray-400">
            <span className="text-gray-500">Comment ID: </span>
            <span className="font-mono text-gray-300">{data.id}</span>
          </div>
        )}

        {data.permalink && (
          <button
            onClick={openComment}
            className="flex items-center gap-1.5 text-sm text-orange-400 transition-colors hover:text-orange-300"
          >
            <ExternalLink className="h-4 w-4" />
            <span>View on Reddit</span>
          </button>
        )}
      </div>
    </div>
  );
}
