"use client";

import RedditCreatedCard from "@/features/reddit/components/RedditCreatedCard";
import type {
  RedditCommentCreatedData,
  RedditPostCreatedData,
} from "@/types/features/redditTypes";

export default function RedditCreatedSection({
  posts = [],
  comments = [],
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
