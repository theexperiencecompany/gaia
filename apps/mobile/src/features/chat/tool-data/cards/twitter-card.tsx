import { useState } from "react";
import { Image, Linking, Pressable, View } from "react-native";
import {
  AppIcon,
  Calendar03Icon,
  CheckmarkCircle02Icon,
  FavouriteIcon,
  LinkSquare02Icon,
  Location01Icon,
  Message01Icon,
  RepeatIcon,
  Share08Icon,
  SquareArrowUpRight02Icon,
  TwitterIcon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { ToolCardHeader, ToolCardInner, ToolCardShell } from "../primitives";

const TWITTER_BLUE = "#1d9bf0";
const TWITTER_LINK = "#1DA1F2";

export interface TwitterUserData {
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
}

export interface TwitterTweetData {
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
}

export interface TwitterSearchData {
  tweets: TwitterTweetData[];
  result_count?: number;
  next_token?: string;
}

function formatNumber(num: number | undefined): string {
  if (!num) return "0";
  if (num >= 1_000_000) return `${(num / 1_000_000).toFixed(1)}M`;
  if (num >= 1_000) return `${(num / 1_000).toFixed(1)}K`;
  return num.toString();
}

function formatTweetDate(dateStr?: string): string {
  if (!dateStr) return "";
  try {
    const d = new Date(dateStr);
    return d.toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  } catch {
    return dateStr;
  }
}

function formatJoinDate(dateStr?: string): string {
  if (!dateStr) return "";
  try {
    const d = new Date(dateStr);
    return d.toLocaleDateString("en-US", {
      month: "long",
      year: "numeric",
    });
  } catch {
    return dateStr;
  }
}

function openTweet(username: string, tweetId: string) {
  Linking.openURL(`https://twitter.com/${username}/status/${tweetId}`);
}

function openUserProfile(username: string) {
  Linking.openURL(`https://twitter.com/${username}`);
}

function Avatar({
  uri,
  name,
  size,
}: {
  uri?: string;
  name: string;
  size: number;
}) {
  const [errored, setErrored] = useState(false);
  const fallbackLetter = (name?.[0] || "?").toUpperCase();

  if (!uri || errored) {
    return (
      <View
        style={{ width: size, height: size }}
        className="rounded-full bg-zinc-700 items-center justify-center overflow-hidden flex-shrink-0"
      >
        <Text
          className="text-zinc-200 font-semibold"
          style={{ fontSize: size * 0.4 }}
        >
          {fallbackLetter}
        </Text>
      </View>
    );
  }

  return (
    <Image
      source={{ uri }}
      onError={() => setErrored(true)}
      style={{ width: size, height: size, borderRadius: size / 2 }}
      className="flex-shrink-0"
    />
  );
}

function EngagementMetric({
  icon,
  value,
  color,
}: {
  icon: React.ComponentType<{ size?: number; color?: string }>;
  value?: number;
  color: string;
}) {
  return (
    <View className="flex-row items-center gap-1.5">
      <AppIcon icon={icon} size={14} color={color} />
      {value !== undefined && (
        <Text className="text-xs text-zinc-500">{formatNumber(value)}</Text>
      )}
    </View>
  );
}

// ---- Tweet row (used in search results) ----

function TweetRow({ tweet }: { tweet: TwitterTweetData }) {
  const author = tweet.author ?? {
    id: "",
    username: "unknown",
    name: "Unknown",
  };
  const metrics = tweet.public_metrics ?? {};

  return (
    <ToolCardInner onPress={() => openTweet(author.username, tweet.id)}>
      <View className="flex-row items-start gap-3">
        <Pressable
          onPress={() => openUserProfile(author.username)}
          className="active:opacity-70"
        >
          <Avatar uri={author.profile_image_url} name={author.name} size={40} />
        </Pressable>

        <View className="flex-1 min-w-0">
          {/* Author row */}
          <View className="flex-row items-center gap-1 flex-wrap">
            <Text
              className="text-sm font-semibold text-zinc-100"
              numberOfLines={1}
            >
              {author.name}
            </Text>
            {author.verified && (
              <AppIcon
                icon={CheckmarkCircle02Icon}
                size={14}
                color={TWITTER_BLUE}
              />
            )}
            <Text className="text-xs text-zinc-500" numberOfLines={1}>
              @{author.username}
            </Text>
            {!!tweet.created_at && (
              <>
                <Text className="text-xs text-zinc-500">·</Text>
                <Text className="text-xs text-zinc-500">
                  {formatTweetDate(tweet.created_at)}
                </Text>
              </>
            )}
          </View>

          {/* Tweet text */}
          <Text className="text-sm text-zinc-200 mt-1 leading-relaxed">
            {tweet.text}
          </Text>

          {/* Engagement row */}
          <View className="flex-row items-center gap-5 mt-3">
            <EngagementMetric
              icon={Message01Icon}
              value={metrics.reply_count}
              color="#71767b"
            />
            <EngagementMetric
              icon={RepeatIcon}
              value={metrics.retweet_count}
              color="#71767b"
            />
            <EngagementMetric
              icon={FavouriteIcon}
              value={metrics.like_count}
              color="#71767b"
            />
            <EngagementMetric icon={Share08Icon} color="#71767b" />
          </View>
        </View>

        <AppIcon icon={LinkSquare02Icon} size={14} color="#71767b" />
      </View>
    </ToolCardInner>
  );
}

// ---- User row (used in users / followers / following lists) ----

function UserRow({ user }: { user: TwitterUserData }) {
  const metrics = user.public_metrics ?? {};
  const hostFromUrl = user.url
    ? user.url.replace(/^https?:\/\//, "").replace(/\/$/, "")
    : undefined;

  return (
    <ToolCardInner onPress={() => openUserProfile(user.username)}>
      <View className="flex-row items-start gap-3">
        <Avatar uri={user.profile_image_url} name={user.name} size={48} />

        <View className="flex-1 min-w-0">
          {/* Name + handle */}
          <View className="flex-row items-center gap-1 flex-wrap">
            <Text className="text-sm font-bold text-zinc-100" numberOfLines={1}>
              {user.name}
            </Text>
            {user.verified && (
              <AppIcon
                icon={CheckmarkCircle02Icon}
                size={14}
                color={TWITTER_BLUE}
              />
            )}
          </View>
          <Text className="text-xs text-zinc-500" numberOfLines={1}>
            @{user.username}
          </Text>

          {/* Bio */}
          {!!user.description && (
            <Text
              className="text-sm text-zinc-200 mt-2 leading-relaxed"
              numberOfLines={3}
            >
              {user.description}
            </Text>
          )}

          {/* Meta row */}
          <View className="flex-row flex-wrap gap-x-3 gap-y-1 mt-2">
            {!!user.location && (
              <View className="flex-row items-center gap-1">
                <AppIcon icon={Location01Icon} size={12} color="#71767b" />
                <Text className="text-xs text-zinc-500">{user.location}</Text>
              </View>
            )}
            {!!hostFromUrl && (
              <View className="flex-row items-center gap-1">
                <AppIcon icon={LinkSquare02Icon} size={12} color="#71767b" />
                <Text
                  className="text-xs"
                  style={{ color: TWITTER_LINK }}
                  numberOfLines={1}
                >
                  {hostFromUrl}
                </Text>
              </View>
            )}
            {!!user.created_at && (
              <View className="flex-row items-center gap-1">
                <AppIcon icon={Calendar03Icon} size={12} color="#71767b" />
                <Text className="text-xs text-zinc-500">
                  Joined {formatJoinDate(user.created_at)}
                </Text>
              </View>
            )}
          </View>

          {/* Stats */}
          <View className="flex-row items-center gap-4 mt-2">
            <View className="flex-row items-center gap-1">
              <Text className="text-sm font-bold text-zinc-100">
                {formatNumber(metrics.following_count)}
              </Text>
              <Text className="text-xs text-zinc-500">Following</Text>
            </View>
            <View className="flex-row items-center gap-1">
              <Text className="text-sm font-bold text-zinc-100">
                {formatNumber(metrics.followers_count)}
              </Text>
              <Text className="text-xs text-zinc-500">Followers</Text>
            </View>
          </View>
        </View>

        <AppIcon icon={SquareArrowUpRight02Icon} size={14} color="#71767b" />
      </View>
    </ToolCardInner>
  );
}

// ---- Top-level card entry points ----

export function TwitterSearchCard({ data }: { data: TwitterSearchData }) {
  const tweets = data?.tweets ?? [];
  const count = data?.result_count ?? tweets.length;

  if (tweets.length === 0) {
    return (
      <ToolCardShell>
        <ToolCardHeader
          icon={TwitterIcon}
          iconColor={TWITTER_BLUE}
          title="Twitter Search"
        />
        <ToolCardInner>
          <Text className="text-sm text-zinc-400">No tweets found.</Text>
        </ToolCardInner>
      </ToolCardShell>
    );
  }

  return (
    <ToolCardShell>
      <ToolCardHeader
        icon={TwitterIcon}
        iconColor={TWITTER_BLUE}
        title="Twitter Search"
        count={count}
      />
      <View className="gap-2">
        {tweets.map((tweet) => (
          <TweetRow key={tweet.id} tweet={tweet} />
        ))}
      </View>
    </ToolCardShell>
  );
}

export function TwitterUserCard({
  data,
  title,
}: {
  data: TwitterUserData[];
  title?: string;
}) {
  const users = data ?? [];

  if (users.length === 0) {
    return (
      <ToolCardShell>
        <ToolCardHeader
          icon={TwitterIcon}
          iconColor={TWITTER_BLUE}
          title={title ?? "Twitter Users"}
        />
        <ToolCardInner>
          <Text className="text-sm text-zinc-400">No users found.</Text>
        </ToolCardInner>
      </ToolCardShell>
    );
  }

  return (
    <ToolCardShell>
      <ToolCardHeader
        icon={TwitterIcon}
        iconColor={TWITTER_BLUE}
        title={title ?? "Twitter Users"}
        count={users.length}
      />
      <View className="gap-2">
        {users.map((user) => (
          <UserRow key={user.id} user={user} />
        ))}
      </View>
    </ToolCardShell>
  );
}
