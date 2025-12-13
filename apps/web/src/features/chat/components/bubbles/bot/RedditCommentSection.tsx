"use client";

import RedditCommentCard from "@/features/reddit/components/RedditCommentCard";
import type { RedditCommentData } from "@/types/features/redditTypes";

export default function RedditCommentSection({
  reddit_comment_data,
}: {
  reddit_comment_data: RedditCommentData[];
}) {
  return (
    <div className="mt-3 w-full">
      <RedditCommentCard comments={reddit_comment_data} />
    </div>
  );
}
