/**
 * Twitter/X data types for frontend rendering.
 *
 * These types match the data streamed from twitter_hooks.py after hooks.
 */

export type TwitterUserData = {
  id: string;
  username: string;
  name: string;
  description?: string;
  profile_image_url?: string;
  verified?: boolean;
  public_metrics?: {
    followers_count?: number;
    following_count?: number;
    tweet_count?: number;
    listed_count?: number;
  };
  created_at?: string;
  location?: string;
  url?: string;
};

export type TwitterTweetData = {
  id: string;
  text: string;
  created_at?: string;
  author: TwitterUserData;
  public_metrics?: {
    retweet_count?: number;
    reply_count?: number;
    like_count?: number;
    quote_count?: number;
    bookmark_count?: number;
    impression_count?: number;
  };
  conversation_id?: string;
};

export type TwitterSearchData = {
  tweets: TwitterTweetData[];
  result_count: number;
  next_token?: string;
};

export type TwitterTimelineData = {
  tweets: TwitterTweetData[];
};

export type TwitterFollowersData = TwitterUserData[];

export type TwitterPostCreatedData = {
  id: string;
  text: string;
  url: string;
};

export type TwitterPostPreviewData = {
  text: string;
  quote_tweet_id?: string;
  reply_to_tweet_id?: string;
  media_ids?: string[];
  poll_options?: string[];
};

/**
 * Unified Twitter data type for tool_data streaming.
 * Matches the payload keys from twitter_hooks.py writer() calls.
 */
export type TwitterData =
  | { type: "search"; data: TwitterSearchData }
  | { type: "timeline"; data: TwitterTimelineData }
  | { type: "users"; data: TwitterUserData[] }
  | { type: "followers"; data: TwitterFollowersData }
  | { type: "following"; data: TwitterFollowersData }
  | { type: "post_created"; data: TwitterPostCreatedData }
  | { type: "post_preview"; data: TwitterPostPreviewData };
