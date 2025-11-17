"use client";

import { Chip } from "@heroui/chip";
import { CheckCircleIcon, ExternalLink } from "lucide-react";

import {
  RedditPostCreatedData,
  RedditCommentCreatedData,
} from "@/types/features/redditTypes";
import { RedditIcon } from "@/components";

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
          <RedditIcon className="text-[#FF4500]" />
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
        <div className="text-sm font-medium text-[#FF4500]">{data.message}</div>

        {data.id && (
          <div className="text-xs text-gray-400">
            <span className="text-gray-500">Post ID: </span>
            <span className="font-mono text-gray-300">{data.id}</span>
          </div>
        )}

        {(data.permalink || data.url) && (
          <button
            onClick={openPost}
            className="flex items-center gap-1.5 text-sm text-[#FF4500] transition-colors hover:text-orange-300"
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
          <RedditIcon className="text-[#FF4500]" />
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
        <div className="text-sm font-medium text-[#FF4500]">{data.message}</div>

        {data.id && (
          <div className="text-xs text-gray-400">
            <span className="text-gray-500">Comment ID: </span>
            <span className="font-mono text-gray-300">{data.id}</span>
          </div>
        )}

        {data.permalink && (
          <button
            onClick={openComment}
            className="flex items-center gap-1.5 text-sm text-[#FF4500] transition-colors hover:text-orange-300"
          >
            <ExternalLink className="h-4 w-4" />
            <span>View on Reddit</span>
          </button>
        )}
      </div>
    </div>
  );
}
