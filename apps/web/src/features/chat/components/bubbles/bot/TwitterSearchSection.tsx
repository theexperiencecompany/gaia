"use client";

import { Avatar, AvatarFallback, AvatarImage } from "@radix-ui/react-avatar";
import { format, parseISO } from "date-fns";
import {
  BadgeCheck,
  ExternalLink,
  Heart,
  MessageCircle,
  Repeat2,
  Share,
} from "lucide-react";
import type { TwitterTweetData } from "@/types/features/twitterTypes";

/**
 * Twitter Card Component - Displays a tweet with author info and engagement metrics.
 * Styled to closely match the real Twitter/X interface.
 */
function TwitterCard({ tweet }: { tweet: TwitterTweetData }) {
  const author = tweet.author || { username: "unknown", name: "Unknown" };
  const metrics = tweet.public_metrics || {};

  const formatNumber = (num: number | undefined) => {
    if (!num) return "0";
    if (num >= 1000000) return `${(num / 1000000).toFixed(1)}M`;
    if (num >= 1000) return `${(num / 1000).toFixed(1)}K`;
    return num.toString();
  };

  const formatDate = (dateStr?: string) => {
    if (!dateStr) return "";
    try {
      return format(parseISO(dateStr), "MMM d, yyyy");
    } catch {
      return dateStr;
    }
  };

  const handleOpenTweet = () => {
    window.open(
      `https://twitter.com/${author.username}/status/${tweet.id}`,
      "_blank",
    );
  };

  return (
    <div
      className="group relative flex w-full flex-col gap-2 rounded-xl border border-default-200 bg-content1/50 p-4 backdrop-blur-sm transition-all hover:border-default-300 hover:bg-content1/70"
      onClick={handleOpenTweet}
    >
      {/* Author Row */}
      <div className="flex items-start gap-3">
        <Avatar className="h-10 w-10 shrink-0 rounded-full overflow-hidden">
          <AvatarImage
            src={author.profile_image_url}
            alt={author.name}
            className="h-full w-full object-cover"
          />
          <AvatarFallback className="flex h-full w-full items-center justify-center bg-primary/10 text-primary text-sm font-semibold">
            {author.name?.[0]?.toUpperCase() || "?"}
          </AvatarFallback>
        </Avatar>

        <div className="flex flex-col min-w-0 flex-1">
          <div className="flex items-center gap-1">
            <span className="font-semibold text-foreground text-sm truncate">
              {author.name}
            </span>
            {author.verified && (
              <BadgeCheck className="h-4 w-4 text-[#1d9bf0] shrink-0" />
            )}
          </div>
          <div className="flex items-center gap-1 text-xs text-default-500">
            <span>@{author.username}</span>
            {tweet.created_at && (
              <>
                <span>·</span>
                <span>{formatDate(tweet.created_at)}</span>
              </>
            )}
          </div>
        </div>

        {/* X Logo in corner */}
        <ExternalLink className="h-4 w-4 text-default-400 opacity-0 group-hover:opacity-100 transition-opacity shrink-0" />
      </div>

      {/* Tweet Text */}
      <p className="text-sm text-foreground leading-relaxed whitespace-pre-wrap">
        {tweet.text}
      </p>

      {/* Engagement Metrics */}
      <div className="flex items-center gap-6 pt-2 text-default-500">
        <div className="flex items-center gap-1.5 text-xs hover:text-[#1d9bf0] transition-colors">
          <MessageCircle className="h-4 w-4" />
          <span>{formatNumber(metrics.reply_count)}</span>
        </div>
        <div className="flex items-center gap-1.5 text-xs hover:text-green-500 transition-colors">
          <Repeat2 className="h-4 w-4" />
          <span>{formatNumber(metrics.retweet_count)}</span>
        </div>
        <div className="flex items-center gap-1.5 text-xs hover:text-pink-500 transition-colors">
          <Heart className="h-4 w-4" />
          <span>{formatNumber(metrics.like_count)}</span>
        </div>
        <div className="flex items-center gap-1.5 text-xs hover:text-[#1d9bf0] transition-colors">
          <Share className="h-4 w-4" />
        </div>
      </div>
    </div>
  );
}

/**
 * Twitter Search Section - Displays a list of tweets from search results.
 */
export default function TwitterSearchSection({
  twitter_search_data,
}: {
  twitter_search_data: {
    tweets: TwitterTweetData[];
    result_count?: number;
    next_token?: string;
  };
}) {
  const { tweets, result_count } = twitter_search_data;

  if (!tweets || tweets.length === 0) {
    return (
      <div className="mt-3 p-4 text-center text-default-500">
        No tweets found.
      </div>
    );
  }

  return (
    <div className="mt-3 flex w-full flex-col gap-3">
      {result_count && (
        <p className="text-xs text-default-500 px-1">
          Found {result_count} tweet{result_count !== 1 ? "s" : ""}
        </p>
      )}
      <div className="flex flex-col gap-2">
        {tweets.map((tweet) => (
          <TwitterCard key={tweet.id} tweet={tweet} />
        ))}
      </div>
    </div>
  );
}
