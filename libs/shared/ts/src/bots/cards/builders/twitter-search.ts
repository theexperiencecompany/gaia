import type { TwitterSearchData, TwitterTweetData } from "../../../chat/types";
import { formatDate } from "../../../utils/dateUtils";
import type { Card, CardListItem } from "../types";
import { cappedList, countOf, joinMeta, snippet } from "./card-parts";
import { xNameWithHandle, xPostUrl } from "./twitter-links";

const SEARCH_TITLE = "Posts on X";
/** Past this many the list stops and says how many more there are. */
const MAX_LISTED_POSTS = 6;
/** A post is short; this only trims the rare long one. */
const POST_TEXT_MAX = 280;

function engagement(tweet: TwitterTweetData): (string | null)[] {
  const metrics = tweet.public_metrics;
  return [
    countOf(metrics?.like_count, "like"),
    countOf(metrics?.reply_count, "reply", "replies"),
    countOf(metrics?.retweet_count, "repost"),
  ];
}

function postItem(tweet: TwitterTweetData): CardListItem {
  return {
    title: xNameWithHandle(tweet.author),
    url: xPostUrl(tweet.author.username, tweet.id),
    meta: joinMeta([
      tweet.created_at ? formatDate(tweet.created_at) : null,
      ...engagement(tweet),
    ]),
    body: snippet(tweet.text, POST_TEXT_MAX),
  };
}

/** The posts an X search found, each opening on X. */
export function buildTwitterSearchCards(data: TwitterSearchData): Card[] {
  if (data.tweets.length === 0) return [];
  return [
    {
      title: SEARCH_TITLE,
      accent: "brand",
      blocks: [cappedList(data.tweets, MAX_LISTED_POSTS, postItem)],
      actions: [],
    },
  ];
}
