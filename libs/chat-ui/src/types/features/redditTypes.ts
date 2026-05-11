export type RedditPostData = {
  id: string;
  title: string;
  author: string;
  subreddit: string; // e.g., "r/webdev"
  score: number; // upvotes - downvotes
  upvote_ratio?: number; // 0-1, percentage of upvotes
  num_comments: number;
  created_utc: number; // Unix timestamp
  selftext?: string; // Text content for self posts
  url?: string; // URL for link posts
  permalink?: string; // Reddit permalink
  is_self?: boolean; // Whether it's a text post
  link_flair_text?: string; // Post flair
};

export type RedditCommentData = {
  id: string;
  author: string;
  body: string; // Comment text content
  score: number; // upvotes - downvotes
  created_utc: number; // Unix timestamp
  permalink?: string; // Reddit permalink
  is_submitter?: boolean; // Whether the comment author is the post author
};

export type RedditSearchData = {
  id: string;
  title: string;
  author: string;
  subreddit: string; // e.g., "r/webdev"
  score: number;
  num_comments: number;
  created_utc: number;
  permalink?: string;
  url?: string;
  selftext?: string; // Preview of text content
};

export type RedditPostCreatedData = {
  id: string;
  url?: string;
  message: string;
  permalink?: string;
};

export type RedditCommentCreatedData = {
  id: string;
  message: string;
  permalink?: string;
};

// Unified Reddit data type that can handle all Reddit operations
export type RedditData =
  | { type: "search"; posts: RedditSearchData[] }
  | { type: "post"; post: RedditPostData }
  | { type: "comments"; comments: RedditCommentData[] }
  | { type: "post_created"; data: RedditPostCreatedData }
  | { type: "comment_created"; data: RedditCommentCreatedData };
