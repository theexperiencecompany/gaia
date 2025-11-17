"use client";

import RedditSearchCard from "@/features/reddit/components/RedditSearchCard";
import { RedditSearchData } from "@/types/features/redditTypes";

export default function RedditSearchSection({
  reddit_search_data,
}: {
  reddit_search_data: RedditSearchData[];
}) {
  return (
    <div className="mt-3 w-full">
      <RedditSearchCard posts={reddit_search_data} />
    </div>
  );
}
