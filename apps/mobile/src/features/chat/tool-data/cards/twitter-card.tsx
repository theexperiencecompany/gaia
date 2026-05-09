import { Image } from "expo-image";
import { useState } from "react";
import { Linking, Pressable, View } from "react-native";
import {
  AppIcon,
  Calendar01Icon,
  CheckmarkBadge02Icon,
  FavouriteIcon,
  LinkIcon,
  MapsIcon,
  MessageIcon,
  RepeatIcon,
  ShareIcon,
  TwitterIcon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";

// Twitter brand colors
const TWITTER_BLUE = "#1d9bf0";

// Card contract — DESIGN.md §12
const CARD_BG = "#27272a"; // zinc-800
const ITEM_BG = "#18181b"; // zinc-900
const TEXT_PRIMARY = "#f4f4f5"; // zinc-100
const TEXT_SECONDARY = "#a1a1aa"; // zinc-400
const TEXT_TERTIARY = "#71717a"; // zinc-500

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

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

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
    if (Number.isNaN(d.getTime())) return dateStr;
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
    if (Number.isNaN(d.getTime())) return dateStr;
    return d.toLocaleDateString("en-US", { month: "long", year: "numeric" });
  } catch {
    return dateStr;
  }
}

function stripUrlPrefix(url: string): string {
  return url.replace(/^https?:\/\//, "").replace(/\/$/, "");
}

function openTweet(author: { username?: string }, tweetId: string) {
  const username = author.username || "i";
  Linking.openURL(`https://twitter.com/${username}/status/${tweetId}`);
}

function openProfile(username: string) {
  Linking.openURL(`https://twitter.com/${username}`);
}

// ---------------------------------------------------------------------------
// Shared sub-components
// ---------------------------------------------------------------------------

function Avatar({
  uri,
  name,
  size,
}: {
  uri?: string;
  name?: string;
  size: number;
}) {
  const [errored, setErrored] = useState(false);
  const initial = (name?.[0] || "?").toUpperCase();

  if (!uri || errored) {
    return (
      <View
        style={{
          width: size,
          height: size,
          borderRadius: size / 2,
          backgroundColor: "rgba(29, 155, 240, 0.15)",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <Text
          style={{
            color: TWITTER_BLUE,
            fontSize: size * 0.4,
            fontWeight: "600",
          }}
        >
          {initial}
        </Text>
      </View>
    );
  }

  return (
    <Image
      source={{ uri }}
      style={{ width: size, height: size, borderRadius: size / 2 }}
      onError={() => setErrored(true)}
      contentFit="cover"
      transition={150}
    />
  );
}

function VerifiedBadge() {
  return <AppIcon icon={CheckmarkBadge02Icon} size={14} color={TWITTER_BLUE} />;
}

function TwitterCardHeader({ count, label }: { count: number; label: string }) {
  return (
    <View
      style={{
        flexDirection: "row",
        alignItems: "center",
        gap: 8,
        marginBottom: 12,
      }}
    >
      <View
        style={{
          width: 24,
          height: 24,
          borderRadius: 6,
          backgroundColor: "rgba(29, 155, 240, 0.15)",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <AppIcon icon={TwitterIcon} size={14} color={TWITTER_BLUE} />
      </View>
      <Text
        style={{
          fontSize: 13,
          fontWeight: "600",
          color: TEXT_PRIMARY,
          flex: 1,
        }}
      >
        {label}
      </Text>
      <View
        style={{
          backgroundColor: "rgba(255,255,255,0.06)",
          paddingHorizontal: 8,
          paddingVertical: 2,
          borderRadius: 999,
        }}
      >
        <Text style={{ fontSize: 11, color: TEXT_SECONDARY }}>
          {count} {count === 1 ? "result" : "results"}
        </Text>
      </View>
    </View>
  );
}

// ---------------------------------------------------------------------------
// Tweet item
// ---------------------------------------------------------------------------

function MetricRow({
  icon,
  count,
  color,
}: {
  icon: typeof FavouriteIcon;
  count?: number;
  color: string;
}) {
  return (
    <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
      <AppIcon icon={icon} size={14} color={color} />
      {count !== undefined && (
        <Text style={{ fontSize: 12, color }}>{formatNumber(count)}</Text>
      )}
    </View>
  );
}

function TweetItem({ tweet }: { tweet: TwitterTweetData }) {
  const author =
    tweet.author ||
    ({ username: "unknown", name: "Unknown" } as TwitterUserData);
  const metrics = tweet.public_metrics || {};

  return (
    <Pressable
      onPress={() => openTweet(author, tweet.id)}
      style={({ pressed }) => ({
        backgroundColor: ITEM_BG,
        borderRadius: 16,
        padding: 12,
        opacity: pressed ? 0.85 : 1,
      })}
    >
      {/* Author row */}
      <View style={{ flexDirection: "row", alignItems: "flex-start", gap: 10 }}>
        <Avatar uri={author.profile_image_url} name={author.name} size={40} />

        <View style={{ flex: 1, minWidth: 0 }}>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
            <Text
              style={{
                fontSize: 14,
                fontWeight: "600",
                color: TEXT_PRIMARY,
                flexShrink: 1,
              }}
              numberOfLines={1}
            >
              {author.name}
            </Text>
            {author.verified && <VerifiedBadge />}
          </View>
          <View
            style={{
              flexDirection: "row",
              alignItems: "center",
              gap: 4,
              marginTop: 1,
            }}
          >
            <Text
              style={{ fontSize: 12, color: TEXT_TERTIARY }}
              numberOfLines={1}
            >
              @{author.username}
            </Text>
            {tweet.created_at && (
              <>
                <Text style={{ fontSize: 12, color: TEXT_TERTIARY }}>·</Text>
                <Text style={{ fontSize: 12, color: TEXT_TERTIARY }}>
                  {formatTweetDate(tweet.created_at)}
                </Text>
              </>
            )}
          </View>
        </View>
      </View>

      {/* Tweet text */}
      {!!tweet.text && (
        <Text
          style={{
            fontSize: 14,
            lineHeight: 20,
            color: TEXT_PRIMARY,
            marginTop: 10,
          }}
        >
          {tweet.text}
        </Text>
      )}

      {/* Metrics */}
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          gap: 20,
          marginTop: 12,
        }}
      >
        <MetricRow
          icon={FavouriteIcon}
          count={metrics.like_count}
          color={TEXT_TERTIARY}
        />
        <MetricRow
          icon={MessageIcon}
          count={metrics.reply_count}
          color={TEXT_TERTIARY}
        />
        <MetricRow
          icon={RepeatIcon}
          count={metrics.retweet_count}
          color={TEXT_TERTIARY}
        />
        <View style={{ marginLeft: "auto" }}>
          <MetricRow icon={ShareIcon} color={TEXT_TERTIARY} />
        </View>
      </View>
    </Pressable>
  );
}

// ---------------------------------------------------------------------------
// User profile item
// ---------------------------------------------------------------------------

function UserMetaRow({
  icon,
  label,
  accent,
}: {
  icon: typeof MapsIcon;
  label: string;
  accent?: boolean;
}) {
  return (
    <View style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
      <AppIcon
        icon={icon}
        size={13}
        color={accent ? TWITTER_BLUE : TEXT_TERTIARY}
      />
      <Text
        style={{
          fontSize: 12,
          color: accent ? TWITTER_BLUE : TEXT_TERTIARY,
          maxWidth: 180,
        }}
        numberOfLines={1}
      >
        {label}
      </Text>
    </View>
  );
}

function UserItem({ user }: { user: TwitterUserData }) {
  const metrics = user.public_metrics || {};

  return (
    <Pressable
      onPress={() => openProfile(user.username)}
      style={({ pressed }) => ({
        backgroundColor: ITEM_BG,
        borderRadius: 16,
        padding: 12,
        opacity: pressed ? 0.85 : 1,
      })}
    >
      {/* Header row */}
      <View style={{ flexDirection: "row", alignItems: "flex-start", gap: 10 }}>
        <Avatar uri={user.profile_image_url} name={user.name} size={48} />

        <View style={{ flex: 1, minWidth: 0 }}>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
            <Text
              style={{
                fontSize: 15,
                fontWeight: "700",
                color: TEXT_PRIMARY,
                flexShrink: 1,
              }}
              numberOfLines={1}
            >
              {user.name}
            </Text>
            {user.verified && <VerifiedBadge />}
          </View>
          <Text
            style={{ fontSize: 12, color: TEXT_TERTIARY, marginTop: 1 }}
            numberOfLines={1}
          >
            @{user.username}
          </Text>
        </View>
      </View>

      {/* Bio */}
      {!!user.description && (
        <Text
          style={{
            fontSize: 13,
            lineHeight: 18,
            color: TEXT_PRIMARY,
            marginTop: 10,
          }}
        >
          {user.description}
        </Text>
      )}

      {/* Meta info */}
      {(user.location || user.url || user.created_at) && (
        <View
          style={{
            flexDirection: "row",
            flexWrap: "wrap",
            alignItems: "center",
            gap: 12,
            marginTop: 10,
          }}
        >
          {!!user.location && (
            <UserMetaRow icon={MapsIcon} label={user.location} />
          )}
          {!!user.url && (
            <UserMetaRow
              icon={LinkIcon}
              label={stripUrlPrefix(user.url)}
              accent
            />
          )}
          {!!user.created_at && (
            <UserMetaRow
              icon={Calendar01Icon}
              label={`Joined ${formatJoinDate(user.created_at)}`}
            />
          )}
        </View>
      )}

      {/* Stats */}
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          gap: 16,
          marginTop: 10,
        }}
      >
        <View style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
          <Text
            style={{ fontSize: 13, fontWeight: "700", color: TEXT_PRIMARY }}
          >
            {formatNumber(metrics.following_count)}
          </Text>
          <Text style={{ fontSize: 13, color: TEXT_TERTIARY }}>Following</Text>
        </View>
        <View style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
          <Text
            style={{ fontSize: 13, fontWeight: "700", color: TEXT_PRIMARY }}
          >
            {formatNumber(metrics.followers_count)}
          </Text>
          <Text style={{ fontSize: 13, color: TEXT_TERTIARY }}>Followers</Text>
        </View>
      </View>
    </Pressable>
  );
}

// ---------------------------------------------------------------------------
// Main exports
// ---------------------------------------------------------------------------

export function TwitterSearchCard({ data }: { data: TwitterSearchData }) {
  const tweets = Array.isArray(data?.tweets) ? data.tweets : [];

  if (tweets.length === 0) {
    return (
      <View
        style={{
          marginHorizontal: 16,
          marginVertical: 8,
          borderRadius: 16,
          backgroundColor: CARD_BG,
          padding: 16,
        }}
      >
        <TwitterCardHeader count={0} label="Twitter Search" />
        <Text style={{ fontSize: 13, color: TEXT_TERTIARY }}>
          No tweets found.
        </Text>
      </View>
    );
  }

  const total = data.result_count ?? tweets.length;

  return (
    <View
      style={{
        marginHorizontal: 16,
        marginVertical: 8,
        borderRadius: 16,
        backgroundColor: CARD_BG,
        padding: 16,
      }}
    >
      <TwitterCardHeader count={total} label="Twitter Search" />
      <View style={{ gap: 8 }}>
        {tweets.map((tweet) => (
          <TweetItem key={tweet.id} tweet={tweet} />
        ))}
      </View>
    </View>
  );
}

export function TwitterUserCard({ data }: { data: TwitterUserData[] }) {
  const users = Array.isArray(data) ? data : [];

  if (users.length === 0) {
    return (
      <View
        style={{
          marginHorizontal: 16,
          marginVertical: 8,
          borderRadius: 16,
          backgroundColor: CARD_BG,
          padding: 16,
        }}
      >
        <TwitterCardHeader count={0} label="Twitter Users" />
        <Text style={{ fontSize: 13, color: TEXT_TERTIARY }}>
          No users found.
        </Text>
      </View>
    );
  }

  return (
    <View
      style={{
        marginHorizontal: 16,
        marginVertical: 8,
        borderRadius: 16,
        backgroundColor: CARD_BG,
        padding: 16,
      }}
    >
      <TwitterCardHeader count={users.length} label="Twitter Users" />
      <View style={{ gap: 8 }}>
        {users.map((user) => (
          <UserItem key={user.id} user={user} />
        ))}
      </View>
    </View>
  );
}
