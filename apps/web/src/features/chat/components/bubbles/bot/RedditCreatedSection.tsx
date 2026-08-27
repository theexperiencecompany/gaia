"use client";

import RedditCreatedCard from "@/features/reddit/components/RedditCreatedCard";
import type {
  RedditCommentCreatedData,
  RedditPostCreatedData,
} from "@/types/features/redditTypes";

// Stable empty defaults: inline `= []` creates a new array every render and
// defeats prop-comparison in memoized children.
const EMPTY_POSTS: RedditPostCreatedData[] = [];
const EMPTY_COMMENTS: RedditCommentCreatedData[] = [];

export default function RedditCreatedSection({
  posts = EMPTY_POSTS,
  comments = EMPTY_COMMENTS,
}: {
  posts?: RedditPostCreatedData[];
  comments?: RedditCommentCreatedData[];
}) {
  if (posts.length === 0 && comments.length === 0) return null;

  return (
    <div className="mt-3 w-full">
      <RedditCreatedCard posts={posts} comments={comments} />
    </div>
  );
}
