import type {
  RedditCommentCreatedData,
  RedditCommentData,
  RedditData,
  RedditPostCreatedData,
  RedditPostData,
  RedditSearchData,
} from "@gaia/shared";
import { useState } from "react";
import { Linking, Pressable, View } from "react-native";
import {
  AppIcon,
  ArrowRight01Icon,
  ArrowUp02Icon,
  BubbleChatIcon,
  CheckmarkCircle02Icon,
  LinkSquare02Icon,
  UserCircle02Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import {
  ToolCardHeader,
  ToolCardInner,
  ToolCardShell,
} from "@/features/chat/tool-data/primitives";

const REDDIT_ORANGE = "#FF4500";

function formatTime(timestamp: number): string {
  const date = new Date(timestamp * 1000);
  const now = new Date();
  const diffInSeconds = (now.getTime() - date.getTime()) / 1000;

  if (diffInSeconds < 60) return "Just now";
  if (diffInSeconds < 3600) return `${Math.floor(diffInSeconds / 60)}m ago`;
  if (diffInSeconds < 86400) return `${Math.floor(diffInSeconds / 3600)}h ago`;
  if (diffInSeconds < 604800)
    return `${Math.floor(diffInSeconds / 86400)}d ago`;

  return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function formatNumber(num: number): string {
  if (num >= 1000) return `${(num / 1000).toFixed(1)}k`;
  return num.toString();
}

function openRedditLink(permalink?: string, url?: string) {
  const link = permalink ? `https://reddit.com${permalink}` : url;
  if (link) Linking.openURL(link);
}

// --- Reddit icon (orange circle with "r/") ---

function RedditIconView() {
  return (
    <View
      className="w-8 h-8 rounded-full items-center justify-center"
      style={{ backgroundColor: REDDIT_ORANGE }}
    >
      <Text className="text-white font-bold" style={{ fontSize: 11 }}>
        r/
      </Text>
    </View>
  );
}

// --- Shared sub-components ---

function PostMeta({
  subreddit,
  author,
  createdUtc,
}: {
  subreddit?: string;
  author?: string;
  createdUtc?: number;
}) {
  return (
    <View className="flex-row items-center gap-1.5 flex-wrap mb-1">
      {subreddit && (
        <Text
          className="text-xs font-semibold"
          style={{ color: REDDIT_ORANGE }}
        >
          {subreddit}
        </Text>
      )}
      {author && (
        <>
          <Text className="text-xs text-zinc-500">·</Text>
          <Text className="text-xs text-zinc-500">u/{author}</Text>
        </>
      )}
      {createdUtc !== undefined && (
        <>
          <Text className="text-xs text-zinc-500">·</Text>
          <Text className="text-xs text-zinc-500">
            {formatTime(createdUtc)}
          </Text>
        </>
      )}
    </View>
  );
}

function PostStats({
  score,
  upvoteRatio,
  numComments,
}: {
  score?: number;
  upvoteRatio?: number;
  numComments?: number;
}) {
  return (
    <View className="flex-row items-center gap-4 mt-2">
      {score !== undefined && (
        <View className="flex-row items-center gap-1">
          <AppIcon icon={ArrowUp02Icon} size={14} color={REDDIT_ORANGE} />
          <Text
            className="text-sm font-medium"
            style={{ color: REDDIT_ORANGE }}
          >
            {formatNumber(score)}
          </Text>
          {upvoteRatio !== undefined && (
            <Text className="text-xs text-zinc-500">
              ({Math.round(upvoteRatio * 100)}%)
            </Text>
          )}
        </View>
      )}
      {numComments !== undefined && (
        <View className="flex-row items-center gap-1">
          <AppIcon icon={BubbleChatIcon} size={12} color="#71717a" />
          <Text className="text-xs text-zinc-400">
            {formatNumber(numComments)}
          </Text>
        </View>
      )}
    </View>
  );
}

// --- Search view ---

function SearchView({ posts }: { posts: RedditSearchData[] }) {
  const [expanded, setExpanded] = useState(false);
  const preview = expanded ? posts : posts.slice(0, 3);
  const hasMore = posts.length > 3;

  return (
    <>
      <Text className="text-zinc-500 text-xs mb-2">
        {posts.length} post{posts.length !== 1 ? "s" : ""}
      </Text>

      <View className="gap-1.5">
        {preview.map((post, index) => (
          <ToolCardInner
            key={post.id ?? post.title ?? String(index)}
            dense
            onPress={() => openRedditLink(post.permalink, post.url)}
          >
            <PostMeta
              subreddit={post.subreddit}
              author={post.author}
              createdUtc={post.created_utc}
            />
            <Text
              className="text-sm font-medium text-zinc-200"
              numberOfLines={2}
            >
              {post.title}
            </Text>
            {post.selftext ? (
              <Text className="text-xs text-zinc-400 mt-1" numberOfLines={2}>
                {post.selftext}
              </Text>
            ) : null}
            <PostStats score={post.score} numComments={post.num_comments} />
          </ToolCardInner>
        ))}
      </View>

      {hasMore && (
        <Pressable
          onPress={() => setExpanded((p) => !p)}
          className="mt-2 py-1.5 items-center active:opacity-70"
        >
          <Text
            className="text-xs font-medium"
            style={{ color: REDDIT_ORANGE }}
          >
            {expanded ? "Show less" : `Show all ${posts.length} posts`}
          </Text>
        </Pressable>
      )}
    </>
  );
}

// --- Post view ---

function PostView({ post }: { post: RedditPostData }) {
  const [expanded, setExpanded] = useState(false);
  const hasBody = !!(post.selftext && post.selftext.length > 0);

  return (
    <ToolCardInner>
      <PostMeta
        subreddit={post.subreddit}
        author={post.author}
        createdUtc={post.created_utc}
      />

      <View className="flex-row items-start gap-2">
        <Pressable
          onPress={() => openRedditLink(post.permalink, post.url)}
          className="flex-1 active:opacity-70"
        >
          <Text className="text-base font-semibold text-zinc-100 leading-snug">
            {post.title}
          </Text>
        </Pressable>
        {post.link_flair_text ? (
          <View className="flex-shrink-0 bg-blue-900/30 rounded-full px-2 py-0.5">
            <Text className="text-blue-300 text-xs">
              {post.link_flair_text}
            </Text>
          </View>
        ) : null}
      </View>

      {hasBody && (
        <>
          <Text
            className="text-sm text-zinc-400 mt-2 leading-relaxed"
            numberOfLines={expanded ? undefined : 3}
          >
            {post.selftext}
          </Text>
          <Pressable
            onPress={() => setExpanded((p) => !p)}
            className="mt-1 active:opacity-70"
          >
            <Text
              className="text-xs font-medium"
              style={{ color: REDDIT_ORANGE }}
            >
              {expanded ? "Show less" : "Show more"}
            </Text>
          </Pressable>
        </>
      )}

      {!post.is_self && post.url && (
        <Pressable
          onPress={() => post.url && Linking.openURL(post.url)}
          className="flex-row items-center gap-1 mt-2 active:opacity-70"
        >
          <AppIcon icon={LinkSquare02Icon} size={12} color="#60A5FA" />
          <Text className="text-xs text-blue-400 flex-1" numberOfLines={1}>
            {post.url}
          </Text>
        </Pressable>
      )}

      <View
        style={{
          height: 1,
          backgroundColor: "rgba(255,255,255,0.07)",
          marginVertical: 6,
        }}
      />

      <View className="flex-row items-center justify-between">
        <PostStats
          score={post.score}
          upvoteRatio={post.upvote_ratio}
          numComments={post.num_comments}
        />
        <Pressable
          onPress={() => openRedditLink(post.permalink, post.url)}
          className="flex-row items-center gap-1 active:opacity-70"
        >
          <Text className="text-xs text-zinc-400">View on Reddit</Text>
          <AppIcon icon={ArrowRight01Icon} size={12} color="#71717a" />
        </Pressable>
      </View>
    </ToolCardInner>
  );
}

// --- Comments view ---

function CommentsView({ comments }: { comments: RedditCommentData[] }) {
  const [expanded, setExpanded] = useState(false);
  const preview = expanded ? comments : comments.slice(0, 3);
  const hasMore = comments.length > 3;

  return (
    <>
      <Text className="text-zinc-500 text-xs mb-2">
        {comments.length} comment{comments.length !== 1 ? "s" : ""}
      </Text>

      <View className="gap-1.5">
        {preview.map((comment, index) => (
          <ToolCardInner key={comment.id ?? String(index)} dense>
            {/* Author & meta */}
            <View className="flex-row items-center justify-between mb-2">
              <View className="flex-row items-center gap-1.5">
                <AppIcon icon={UserCircle02Icon} size={13} color="#71717a" />
                <Text
                  className="text-xs font-medium"
                  style={{
                    color: comment.is_submitter ? "#60A5FA" : "#d4d4d8",
                  }}
                >
                  u/{comment.author}
                </Text>
                {comment.is_submitter && (
                  <View className="bg-blue-900/40 rounded px-1.5 py-0.5">
                    <Text className="text-blue-400 text-[10px] font-medium">
                      OP
                    </Text>
                  </View>
                )}
                {comment.created_utc !== undefined && (
                  <>
                    <Text className="text-xs text-zinc-500">·</Text>
                    <Text className="text-xs text-zinc-500">
                      {formatTime(comment.created_utc)}
                    </Text>
                  </>
                )}
              </View>
              {comment.score !== undefined && (
                <View className="flex-row items-center gap-1">
                  <AppIcon
                    icon={ArrowUp02Icon}
                    size={13}
                    color={REDDIT_ORANGE}
                  />
                  <Text
                    className="text-xs font-medium"
                    style={{ color: REDDIT_ORANGE }}
                  >
                    {formatNumber(comment.score)}
                  </Text>
                </View>
              )}
            </View>

            {/* Body */}
            <Text className="text-sm text-zinc-200 leading-relaxed">
              {comment.body}
            </Text>

            {/* Permalink */}
            {comment.permalink && (
              <>
                <View
                  style={{
                    height: 1,
                    backgroundColor: "rgba(255,255,255,0.07)",
                    marginVertical: 6,
                  }}
                />
                <Pressable
                  onPress={() =>
                    comment.permalink &&
                    Linking.openURL(`https://reddit.com${comment.permalink}`)
                  }
                  className="flex-row items-center gap-1 active:opacity-70"
                >
                  <Text
                    className="text-xs font-medium"
                    style={{ color: REDDIT_ORANGE }}
                  >
                    View on Reddit
                  </Text>
                  <AppIcon
                    icon={ArrowRight01Icon}
                    size={12}
                    color={REDDIT_ORANGE}
                  />
                </Pressable>
              </>
            )}
          </ToolCardInner>
        ))}
      </View>

      {hasMore && (
        <Pressable
          onPress={() => setExpanded((p) => !p)}
          className="mt-2 py-1.5 items-center active:opacity-70"
        >
          <Text
            className="text-xs font-medium"
            style={{ color: REDDIT_ORANGE }}
          >
            {expanded ? "Show less" : `Show all ${comments.length} comments`}
          </Text>
        </Pressable>
      )}
    </>
  );
}

// --- Created view ---

function CreatedView({
  type,
  data: itemData,
}: {
  type: "post_created" | "comment_created";
  data: RedditPostCreatedData | RedditCommentCreatedData;
}) {
  const isPost = type === "post_created";
  const permalink = itemData.permalink;
  const url = isPost ? (itemData as RedditPostCreatedData).url : undefined;

  return (
    <ToolCardInner>
      <View className="flex-row items-center gap-2 mb-2">
        <AppIcon icon={CheckmarkCircle02Icon} size={18} color="#4ade80" />
        <Text className="text-sm font-semibold text-green-400">
          {isPost ? "Post Created Successfully" : "Comment Posted Successfully"}
        </Text>
      </View>

      {itemData.message && (
        <Text className="text-sm text-zinc-400 mb-2">{itemData.message}</Text>
      )}

      {itemData.id && (
        <Text className="text-xs text-zinc-500 mb-2">
          ID: <Text className="font-mono text-zinc-300">{itemData.id}</Text>
        </Text>
      )}

      <View
        style={{
          height: 1,
          backgroundColor: "rgba(255,255,255,0.07)",
          marginVertical: 6,
        }}
      />

      {(permalink || url) && (
        <Pressable
          onPress={() => openRedditLink(permalink, url)}
          className="flex-row items-center gap-1.5 active:opacity-70"
        >
          <Text
            className="text-xs font-medium"
            style={{ color: REDDIT_ORANGE }}
          >
            View on Reddit
          </Text>
          <AppIcon icon={ArrowRight01Icon} size={12} color={REDDIT_ORANGE} />
        </Pressable>
      )}
    </ToolCardInner>
  );
}

// --- Main card ---

export function RedditCard({ data }: { data: RedditData }) {
  return (
    <ToolCardShell>
      <ToolCardHeader title="Reddit" trailing={<RedditIconView />} />

      {data.type === "search" && <SearchView posts={data.posts} />}

      {data.type === "post" && <PostView post={data.post} />}

      {data.type === "comments" && <CommentsView comments={data.comments} />}

      {(data.type === "post_created" || data.type === "comment_created") && (
        <CreatedView type={data.type} data={data.data} />
      )}
    </ToolCardShell>
  );
}
