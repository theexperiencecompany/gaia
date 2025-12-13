"use client";

import RedditPostCard from "@/features/reddit/components/RedditPostCard";
import type { RedditPostData } from "@/types/features/redditTypes";

export default function RedditPostSection({
  reddit_post_data,
}: {
  reddit_post_data: RedditPostData;
}) {
  return (
    <div className="mt-3 w-full">
      <RedditPostCard post={reddit_post_data} />
    </div>
  );
}
