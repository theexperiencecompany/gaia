import { Button, Card, Chip, PressableFeedback } from "heroui-native";
import { useState } from "react";
import { Linking, Pressable, View } from "react-native";
import {
  AppIcon,
  ArrowUp02Icon,
  BubbleChatIcon,
  CheckmarkCircle02Icon,
  LinkSquare02Icon,
  UserCircle02Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";

const REDDIT_ORANGE = "#FF4500";

// Reddit "alien" logo as an SVG-free inline representation using text
// We use the brand color + "r/" prefix styling to match the web implementation

export interface RedditPostData {
  id?: string;
  title?: string;
  author?: string;
  subreddit?: string;
  score?: number;
  upvote_ratio?: number;
  num_comments?: number;
  created_utc?: number;
  selftext?: string;
  url?: string;
  permalink?: string;
  is_self?: boolean;
  link_flair_text?: string;
}

export interface RedditCommentData {
  id?: string;
  author?: string;
  body?: string;
  score?: number;
  created_utc?: number;
  permalink?: string;
  is_submitter?: boolean;
}

export interface RedditSearchData {
  id?: string;
  title?: string;
  author?: string;
  subreddit?: string;
  score?: number;
  num_comments?: number;
  created_utc?: number;
  permalink?: string;
  url?: string;
  selftext?: string;
}

export interface RedditPostCreatedData {
  id?: string;
  url?: string;
  message?: string;
  permalink?: string;
}

export interface RedditCommentCreatedData {
  id?: string;
  message?: string;
  permalink?: string;
}

export type RedditData =
  | { type: "search"; posts: RedditSearchData[] }
  | { type: "post"; post: RedditPostData }
  | { type: "comments"; comments: RedditCommentData[] }
  | { type: "post_created"; data: RedditPostCreatedData }
  | { type: "comment_created"; data: RedditCommentCreatedData };

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

// --- Sub-components ---

function RedditHeader() {
  return (
    <View className="flex-row items-center gap-2 mb-3">
      <View
        className="w-6 h-6 rounded-full items-center justify-center"
        style={{ backgroundColor: REDDIT_ORANGE }}
      >
        <Text
          className="text-white font-bold"
          style={{ fontSize: 11, lineHeight: 14 }}
        >
          r/
        </Text>
      </View>
      <Text className="text-xs text-muted font-medium">Reddit</Text>
    </View>
  );
}

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
        <Chip
          size="sm"
          variant="secondary"
          color="default"
          animation="disable-all"
        >
          <Chip.Label style={{ color: REDDIT_ORANGE }}>{subreddit}</Chip.Label>
        </Chip>
      )}
      {author && (
        <>
          <Text className="text-xs text-muted">•</Text>
          <Text className="text-xs text-muted">u/{author}</Text>
        </>
      )}
      {createdUtc !== undefined && (
        <>
          <Text className="text-xs text-muted">•</Text>
          <Text className="text-xs text-muted">{formatTime(createdUtc)}</Text>
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
          <AppIcon icon={ArrowUp02Icon} size={16} color={REDDIT_ORANGE} />
          <Text
            className="text-sm font-medium"
            style={{ color: REDDIT_ORANGE }}
          >
            {formatNumber(score)}
          </Text>
          {upvoteRatio !== undefined && (
            <Text className="text-xs text-muted">
              ({Math.round(upvoteRatio * 100)}%)
            </Text>
          )}
        </View>
      )}
      {numComments !== undefined && (
        <View className="flex-row items-center gap-1">
          <AppIcon icon={BubbleChatIcon} size={14} color="#8e8e93" />
          <Text className="text-xs text-muted">
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
      <View className="flex-row items-center justify-between mb-2">
        <Chip
          size="sm"
          variant="secondary"
          color="default"
          animation="disable-all"
        >
          <Chip.Label>
            {posts.length} post{posts.length !== 1 ? "s" : ""}
          </Chip.Label>
        </Chip>
      </View>

      <View className="rounded-xl bg-white/5 border border-white/10 overflow-hidden">
        {preview.map((post, index) => (
          <View key={post.id ?? post.title ?? String(index)}>
            <PressableFeedback
              onPress={() => openRedditLink(post.permalink, post.url)}
            >
              <View className="p-3">
                <PostMeta
                  subreddit={post.subreddit}
                  author={post.author}
                  createdUtc={post.created_utc}
                />
                <Text
                  className="text-sm font-medium text-foreground"
                  numberOfLines={2}
                >
                  {post.title}
                </Text>
                {post.selftext ? (
                  <Text className="text-xs text-muted mt-1" numberOfLines={2}>
                    {post.selftext}
                  </Text>
                ) : null}
                <PostStats score={post.score} numComments={post.num_comments} />
              </View>
            </PressableFeedback>
            {index < preview.length - 1 && (
              <View
                style={{
                  height: 1,
                  backgroundColor: "rgba(255,255,255,0.07)",
                  marginVertical: 4,
                }}
              />
            )}
          </View>
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
  const hasFlair = !!post.link_flair_text;

  return (
    <View className="rounded-xl bg-white/5 border border-white/10 p-3">
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
          <Text className="text-base font-semibold text-foreground leading-snug">
            {post.title}
          </Text>
        </Pressable>
        {hasFlair && (
          <Chip
            size="sm"
            variant="secondary"
            color="default"
            animation="disable-all"
            className="flex-shrink-0"
          >
            <Chip.Label className="text-blue-300">
              {post.link_flair_text}
            </Chip.Label>
          </Chip>
        )}
      </View>

      {hasBody && (
        <>
          <Text
            className="text-sm text-muted mt-2 leading-relaxed"
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
          marginVertical: 4,
        }}
      />

      <View className="flex-row items-center justify-between mt-1">
        <PostStats
          score={post.score}
          upvoteRatio={post.upvote_ratio}
          numComments={post.num_comments}
        />
        <Button
          size="sm"
          variant="ghost"
          onPress={() => openRedditLink(post.permalink, post.url)}
        >
          <Button.Label className="text-muted">View on Reddit →</Button.Label>
        </Button>
      </View>
    </View>
  );
}

// --- Comments view ---

function CommentsView({ comments }: { comments: RedditCommentData[] }) {
  const [expanded, setExpanded] = useState(false);
  const preview = expanded ? comments : comments.slice(0, 3);
  const hasMore = comments.length > 3;

  return (
    <>
      <View className="flex-row items-center justify-between mb-2">
        <Chip
          size="sm"
          variant="secondary"
          color="default"
          animation="disable-all"
        >
          <Chip.Label>
            {comments.length} comment{comments.length !== 1 ? "s" : ""}
          </Chip.Label>
        </Chip>
      </View>

      <View className="gap-2">
        {preview.map((comment, index) => (
          <View
            key={comment.id ?? String(index)}
            className="rounded-xl border border-white/10 bg-white/5 p-3"
          >
            {/* Author & meta */}
            <View className="flex-row items-center justify-between mb-2">
              <View className="flex-row items-center gap-1.5">
                <AppIcon icon={UserCircle02Icon} size={14} color="#8e8e93" />
                <Text
                  className="text-xs font-medium"
                  style={{
                    color: comment.is_submitter ? "#60A5FA" : "#d1d5db",
                  }}
                >
                  u/{comment.author}
                </Text>
                {comment.is_submitter && (
                  <Chip
                    size="sm"
                    variant="secondary"
                    color="default"
                    animation="disable-all"
                  >
                    <Chip.Label className="text-blue-400">OP</Chip.Label>
                  </Chip>
                )}
                {comment.created_utc !== undefined && (
                  <>
                    <Text className="text-xs text-muted">•</Text>
                    <Text className="text-xs text-muted">
                      {formatTime(comment.created_utc)}
                    </Text>
                  </>
                )}
              </View>
              {comment.score !== undefined && (
                <View className="flex-row items-center gap-1">
                  <AppIcon
                    icon={ArrowUp02Icon}
                    size={14}
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
            <Text className="text-sm text-foreground/90 leading-relaxed">
              {comment.body}
            </Text>

            {/* Link */}
            {comment.permalink && (
              <>
                <View
                  style={{
                    height: 1,
                    backgroundColor: "rgba(255,255,255,0.07)",
                    marginVertical: 4,
                  }}
                />
                <Pressable
                  onPress={() =>
                    comment.permalink &&
                    Linking.openURL(`https://reddit.com${comment.permalink}`)
                  }
                  className="active:opacity-70"
                >
                  <Text
                    className="text-xs font-medium"
                    style={{ color: REDDIT_ORANGE }}
                  >
                    View on Reddit →
                  </Text>
                </Pressable>
              </>
            )}
          </View>
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
    <View className="rounded-xl bg-white/5 border border-white/10 p-3">
      <View className="flex-row items-center gap-2 mb-2">
        <AppIcon icon={CheckmarkCircle02Icon} size={18} color="#4ade80" />
        <Text className="text-sm font-semibold text-green-400">
          {isPost
            ? "Post Created Successfully!"
            : "Comment Posted Successfully!"}
        </Text>
      </View>

      {itemData.message && (
        <Text className="text-sm text-muted mb-2">{itemData.message}</Text>
      )}

      {itemData.id && (
        <Text className="text-xs text-muted mb-2">
          ID:{" "}
          <Text className="font-mono text-foreground/70">{itemData.id}</Text>
        </Text>
      )}

      <View
        style={{
          height: 1,
          backgroundColor: "rgba(255,255,255,0.07)",
          marginVertical: 4,
        }}
      />

      <View className="flex-row items-center justify-between">
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
            <AppIcon icon={LinkSquare02Icon} size={12} color={REDDIT_ORANGE} />
          </Pressable>
        )}
        <Chip
          size="sm"
          variant="secondary"
          color="success"
          animation="disable-all"
          className="ml-auto"
        >
          <Chip.Label>Just now</Chip.Label>
        </Chip>
      </View>
    </View>
  );
}

// --- Main card ---

export function RedditCard({ data }: { data: RedditData }) {
  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-2xl bg-[#171920]">
      <Card.Body className="py-3 px-4">
        <RedditHeader />

        {data.type === "search" && <SearchView posts={data.posts} />}

        {data.type === "post" && <PostView post={data.post} />}

        {data.type === "comments" && <CommentsView comments={data.comments} />}

        {(data.type === "post_created" || data.type === "comment_created") && (
          <CreatedView type={data.type} data={data.data} />
        )}
      </Card.Body>
    </Card>
  );
}
