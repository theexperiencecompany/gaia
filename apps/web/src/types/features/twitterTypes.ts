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
