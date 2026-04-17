import type {
  TwitterSearchData,
  TwitterTweetData,
  TwitterUserData,
} from "@gaia/shared";
import { Image, Linking, View } from "react-native";
import {
  AppIcon,
  BubbleChatIcon,
  Calendar03Icon,
  CheckmarkCircle01Icon,
  FavouriteIcon,
  Globe02Icon,
  LinkSquare02Icon,
  Location01Icon,
  RepeatIcon,
  TwitterIcon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import {
  ToolCardHeader,
  ToolCardInner,
  ToolCardShell,
} from "@/features/chat/tool-data/primitives";

// -- Helpers -----------------------------------------------------------------

function formatNumber(num?: number): string {
  if (num === undefined || num === null) return "0";
  if (num >= 1_000_000) return `${(num / 1_000_000).toFixed(1)}M`;
  if (num >= 1_000) return `${(num / 1_000).toFixed(1)}K`;
  return num.toString();
}

function formatDate(dateStr?: string): string {
  if (!dateStr) return "";
  const date = new Date(dateStr);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function formatJoinDate(dateStr?: string): string {
  if (!dateStr) return "";
  const date = new Date(dateStr);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString("en-US", {
    month: "long",
    year: "numeric",
  });
}

function openTweet(tweet: TwitterTweetData) {
  const username = tweet.author?.username;
  if (!username || !tweet.id) return;
  Linking.openURL(`https://twitter.com/${username}/status/${tweet.id}`);
}

function openUserProfile(user: TwitterUserData) {
  const url = user.url ?? `https://twitter.com/${user.username}`;
  Linking.openURL(url);
}

// -- Avatar ------------------------------------------------------------------

function TwitterAvatar({
  url,
  fallback,
  size = 36,
}: {
  url?: string;
  fallback: string;
  size?: number;
}) {
  if (url) {
    return (
      <Image
        source={{ uri: url }}
        style={{ width: size, height: size, borderRadius: size / 2 }}
        resizeMode="cover"
      />
    );
  }
  return (
    <View
      className="items-center justify-center bg-zinc-700"
      style={{ width: size, height: size, borderRadius: size / 2 }}
    >
      <Text className="text-zinc-200 text-sm font-semibold">
        {fallback.charAt(0).toUpperCase() || "?"}
      </Text>
    </View>
  );
}

// -- Tweet row ---------------------------------------------------------------

function TweetRow({ tweet }: { tweet: TwitterTweetData }) {
  const author = tweet.author ?? {
    id: "",
    username: "unknown",
    name: "Unknown",
  };
  const metrics = tweet.public_metrics ?? {};

  return (
    <ToolCardInner dense onPress={() => openTweet(tweet)}>
      <View className="flex-row items-start gap-3">
        <TwitterAvatar url={author.profile_image_url} fallback={author.name} />
        <View className="flex-1 min-w-0">
          {/* Author header */}
          <View className="flex-row items-center gap-1 flex-wrap">
            <Text
              className="text-zinc-100 text-sm font-semibold"
              numberOfLines={1}
            >
              {author.name}
            </Text>
            {author.verified && (
              <AppIcon icon={CheckmarkCircle01Icon} size={13} color="#1d9bf0" />
            )}
            <Text className="text-zinc-500 text-xs" numberOfLines={1}>
              @{author.username}
            </Text>
            {tweet.created_at ? (
              <>
                <Text className="text-zinc-500 text-xs">·</Text>
                <Text className="text-zinc-500 text-xs" numberOfLines={1}>
                  {formatDate(tweet.created_at)}
                </Text>
              </>
            ) : null}
          </View>
          {/* Tweet body */}
          <Text className="text-zinc-200 text-sm mt-1 leading-relaxed">
            {tweet.text}
          </Text>
          {/* Engagement metrics */}
          <View className="flex-row items-center gap-5 mt-2">
            <View className="flex-row items-center gap-1.5">
              <AppIcon icon={FavouriteIcon} size={12} color="#a1a1aa" />
              <Text className="text-zinc-400 text-xs">
                {formatNumber(metrics.like_count)}
              </Text>
            </View>
            <View className="flex-row items-center gap-1.5">
              <AppIcon icon={BubbleChatIcon} size={12} color="#a1a1aa" />
              <Text className="text-zinc-400 text-xs">
                {formatNumber(metrics.reply_count)}
              </Text>
            </View>
            <View className="flex-row items-center gap-1.5">
              <AppIcon icon={RepeatIcon} size={12} color="#a1a1aa" />
              <Text className="text-zinc-400 text-xs">
                {formatNumber(metrics.retweet_count)}
              </Text>
            </View>
          </View>
        </View>
        <AppIcon icon={LinkSquare02Icon} size={12} color="#52525b" />
      </View>
    </ToolCardInner>
  );
}

// -- User row ----------------------------------------------------------------

function UserRow({ user }: { user: TwitterUserData }) {
  const metrics = user.public_metrics ?? {};

  return (
    <ToolCardInner dense onPress={() => openUserProfile(user)}>
      <View className="flex-row items-start gap-3">
        <TwitterAvatar
          url={user.profile_image_url}
          fallback={user.name}
          size={40}
        />
        <View className="flex-1 min-w-0">
          {/* Name + verified + handle */}
          <View className="flex-row items-center gap-1 flex-wrap">
            <Text className="text-zinc-100 text-sm font-bold" numberOfLines={1}>
              {user.name}
            </Text>
            {user.verified && (
              <AppIcon icon={CheckmarkCircle01Icon} size={13} color="#1d9bf0" />
            )}
          </View>
          <Text className="text-zinc-500 text-xs" numberOfLines={1}>
            @{user.username}
          </Text>

          {/* Bio */}
          {user.description ? (
            <Text
              className="text-zinc-200 text-sm mt-1.5 leading-relaxed"
              numberOfLines={3}
            >
              {user.description}
            </Text>
          ) : null}

          {/* Meta: location, url, join date */}
          {user.location || user.url || user.created_at ? (
            <View className="flex-row items-center flex-wrap gap-x-3 gap-y-1 mt-1.5">
              {user.location ? (
                <View className="flex-row items-center gap-1">
                  <AppIcon icon={Location01Icon} size={12} color="#71717a" />
                  <Text className="text-zinc-500 text-xs">{user.location}</Text>
                </View>
              ) : null}
              {user.url ? (
                <View className="flex-row items-center gap-1">
                  <AppIcon icon={Globe02Icon} size={12} color="#71717a" />
                  <Text className="text-[#1d9bf0] text-xs" numberOfLines={1}>
                    {user.url.replace(/^https?:\/\//, "").replace(/\/$/, "")}
                  </Text>
                </View>
              ) : null}
              {user.created_at ? (
                <View className="flex-row items-center gap-1">
                  <AppIcon icon={Calendar03Icon} size={12} color="#71717a" />
                  <Text className="text-zinc-500 text-xs">
                    Joined {formatJoinDate(user.created_at)}
                  </Text>
                </View>
              ) : null}
            </View>
          ) : null}

          {/* Following / Followers stats */}
          <View className="flex-row items-center gap-4 mt-2">
            {metrics.following_count !== undefined && (
              <View className="flex-row items-center gap-1">
                <Text className="text-zinc-100 text-sm font-bold">
                  {formatNumber(metrics.following_count)}
                </Text>
                <Text className="text-zinc-500 text-xs">Following</Text>
              </View>
            )}
            {metrics.followers_count !== undefined && (
              <View className="flex-row items-center gap-1">
                <Text className="text-zinc-100 text-sm font-bold">
                  {formatNumber(metrics.followers_count)}
                </Text>
                <Text className="text-zinc-500 text-xs">Followers</Text>
              </View>
            )}
          </View>
        </View>
        <AppIcon icon={LinkSquare02Icon} size={12} color="#52525b" />
      </View>
    </ToolCardInner>
  );
}

// -- Main cards --------------------------------------------------------------

export function TwitterSearchCard({ data }: { data: TwitterSearchData }) {
  const tweets = data.tweets ?? [];
  const resultCount = data.result_count ?? tweets.length;

  return (
    <ToolCardShell>
      <ToolCardHeader
        icon={TwitterIcon}
        iconColor="#1d9bf0"
        title="Twitter"
        subtitle={
          resultCount > 0
            ? `${resultCount} tweet${resultCount !== 1 ? "s" : ""}`
            : undefined
        }
        count={tweets.length}
      />
      {tweets.length === 0 ? (
        <Text className="text-zinc-500 text-sm">No tweets found</Text>
      ) : (
        <View className="gap-1.5">
          {tweets.map((tweet) => (
            <TweetRow key={tweet.id} tweet={tweet} />
          ))}
        </View>
      )}
    </ToolCardShell>
  );
}

export function TwitterUserCard({ data }: { data: TwitterUserData[] }) {
  const users = Array.isArray(data) ? data : [];

  return (
    <ToolCardShell>
      <ToolCardHeader
        icon={TwitterIcon}
        iconColor="#1d9bf0"
        title="Twitter Profiles"
        count={users.length}
      />
      {users.length === 0 ? (
        <Text className="text-zinc-500 text-sm">No users found</Text>
      ) : (
        <View className="gap-1.5">
          {users.map((user) => (
            <UserRow key={user.id} user={user} />
          ))}
        </View>
      )}
    </ToolCardShell>
  );
}
