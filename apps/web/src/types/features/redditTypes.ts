import type { RedditDataCard } from "@shared/api/generated";

export type {
  RedditCardComment as RedditCommentData,
  RedditCardCommentCreated as RedditCommentCreatedData,
  RedditCardPost as RedditPostData,
  RedditCardPostCreated as RedditPostCreatedData,
  RedditCardSearchPost as RedditSearchData,
} from "@shared/api/generated";

/** One reddit_data card: a search, a post, its comments, or a post or comment the user created. */
export type RedditData = RedditDataCard["data"];
