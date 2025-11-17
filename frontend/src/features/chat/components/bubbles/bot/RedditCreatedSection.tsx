"use client";

import {
  RedditCommentCreatedCard,
  RedditPostCreatedCard,
} from "@/features/reddit/components/RedditCreatedCard";
import {
  RedditCommentCreatedData,
  RedditPostCreatedData,
} from "@/types/features/redditTypes";

export function RedditPostCreatedSection({
  reddit_post_created_data,
}: {
  reddit_post_created_data: RedditPostCreatedData;
}) {
  return (
    <div className="mt-3 w-full">
      <RedditPostCreatedCard data={reddit_post_created_data} />
    </div>
  );
}

export function RedditCommentCreatedSection({
  reddit_comment_created_data,
}: {
  reddit_comment_created_data: RedditCommentCreatedData;
}) {
  return (
    <div className="mt-3 w-full">
      <RedditCommentCreatedCard data={reddit_comment_created_data} />
    </div>
  );
}
