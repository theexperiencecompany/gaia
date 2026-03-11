import { Button, Card, Chip } from "heroui-native";
import { useMemo, useState } from "react";
import { Linking, Pressable, View } from "react-native";
import {
  Alert01Icon,
  AppIcon,
  ArrowDown01Icon,
  Calendar03Icon,
  CheckmarkCircle02Icon,
  Clock01Icon,
  CodeIcon,
  CpuIcon,
  DocumentAttachmentIcon,
  FavouriteIcon,
  FlashIcon,
  FlowIcon,
  MessageMultiple01Icon,
  RepeatIcon,
  Settings01Icon,
  Share08Icon,
  TwitterIcon,
  UploadCircle01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";

// ---------------------------------------------------------------------------
// Interfaces
// ---------------------------------------------------------------------------

interface ToolCallEntry {
  tool_call_id?: string;
  tool_name?: string;
  tool_category?: string;
  inputs?: Record<string, unknown>;
  message?: string;
  output?: string;
  integration_name?: string;
  show_category?: boolean;
}

interface ArtifactItem {
  filename?: string;
  path?: string;
  size_bytes?: number;
  content_type?: string;
}

interface RateLimitData {
  feature?: string;
  plan_required?: string;
  reset_time?: string;
}

interface WorkflowDraftData {
  suggested_title?: string;
  suggested_description?: string;
  trigger_type?: string;
  cron_expression?: string;
  trigger_slug?: string;
}

interface WorkflowCreatedData {
  title?: string;
  description?: string;
  activated?: boolean;
  trigger_config?: {
    type?: string;
    cron_expression?: string;
    trigger_name?: string;
  };
}

interface TwitterAuthor {
  username?: string;
  name?: string;
  verified?: boolean;
  profile_image_url?: string;
}

interface TwitterTweetData {
  id?: string;
  text?: string;
  created_at?: string;
  author?: TwitterAuthor;
  public_metrics?: {
    like_count?: number;
    reply_count?: number;
    retweet_count?: number;
  };
}

interface TwitterUserData {
  id?: string;
  username?: string;
  name?: string;
  description?: string;
  verified?: boolean;
  location?: string;
  url?: string;
  created_at?: string;
  public_metrics?: {
    followers_count?: number;
    following_count?: number;
    tweet_count?: number;
  };
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const formatBytes = (size?: number): string => {
  if (!size || size < 0) return "Unknown size";
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
};

const formatFeatureName = (feature?: string): string => {
  if (!feature) return "This feature";
  return feature
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
};

const formatResetTime = (resetTime?: string): string | null => {
  if (!resetTime) return null;
  const parsed = new Date(resetTime);
  if (Number.isNaN(parsed.getTime())) return null;
  const diffMs = parsed.getTime() - Date.now();
  if (diffMs <= 0) return "Resets very soon";
  const mins = Math.ceil(diffMs / 60000);
  if (mins > 60) {
    const hours = Math.ceil(mins / 60);
    return `Resets in ${hours} hour${hours > 1 ? "s" : ""}`;
  }
  return `Resets in ${mins} minute${mins > 1 ? "s" : ""}`;
};

const getResetDetail = (resetTime?: string): string | null => {
  if (!resetTime) return null;
  const parsed = new Date(resetTime);
  if (Number.isNaN(parsed.getTime())) return null;
  return `Available again at ${parsed.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
};

const getExtLabel = (filename?: string, contentType?: string): string => {
  if (filename?.includes(".")) {
    return filename.split(".").pop()?.toUpperCase() || "FILE";
  }
  if (contentType?.includes("json")) return "JSON";
  if (contentType?.includes("html")) return "HTML";
  if (contentType?.includes("markdown")) return "MD";
  if (contentType?.includes("text")) return "TXT";
  return "FILE";
};

const formatNumber = (num?: number): string => {
  if (!num) return "0";
  if (num >= 1_000_000) return `${(num / 1_000_000).toFixed(1)}M`;
  if (num >= 1_000) return `${(num / 1_000).toFixed(1)}K`;
  return num.toString();
};

const formatTweetDate = (dateStr?: string): string => {
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
};

const formatJoinDate = (dateStr?: string): string => {
  if (!dateStr) return "";
  try {
    const d = new Date(dateStr);
    return d.toLocaleDateString("en-US", { month: "long", year: "numeric" });
  } catch {
    return dateStr;
  }
};

const getTriggerInfo = (
  triggerType?: string,
  triggerLabel?: string,
): { label: string; color: string; bg: string } => {
  switch (triggerType) {
    case "manual":
      return { label: "Manual", color: "text-[#8e8e93]", bg: "bg-white/10" };
    case "scheduled":
      return {
        label: triggerLabel || "Scheduled",
        color: "text-primary",
        bg: "bg-primary/15",
      };
    case "integration":
      return {
        label: triggerLabel || "Integration",
        color: "text-purple-400",
        bg: "bg-purple-500/15",
      };
    default:
      return { label: "Unknown", color: "text-[#8e8e93]", bg: "bg-white/10" };
  }
};

const getToolCategoryLabel = (tool: ToolCallEntry): string => {
  if (tool.integration_name) return tool.integration_name;
  const cat = tool.tool_category;
  if (!cat || cat === "unknown") return "";
  return cat
    .replace(/_/g, " ")
    .split(" ")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
    .join(" ");
};

// ---------------------------------------------------------------------------
// ToolCallsCard
// ---------------------------------------------------------------------------

export function ToolCallsCard({ data }: { data: unknown }) {
  const calls = (Array.isArray(data) ? data : [data]) as ToolCallEntry[];
  const [openCallIds, setOpenCallIds] = useState<Record<string, boolean>>({});

  const uniqueToolsCount = useMemo(() => {
    const set = new Set(
      calls.map((call) => call.tool_category || call.tool_name),
    );
    return set.size;
  }, [calls]);

  const toggle = (id: string) => {
    setOpenCallIds((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-2xl bg-[#171920]">
      <Card.Body className="py-3 px-4">
        {/* Header */}
        <View className="flex-row items-center justify-between mb-3">
          <View className="flex-row items-center gap-2">
            <View className="w-5 h-5 rounded-md bg-white/10 items-center justify-center">
              <AppIcon
                icon={CpuIcon}
                size={12}
                color="#8e8e93"
                strokeWidth={2}
              />
            </View>
            <Text className="text-xs font-medium text-[#8e8e93]">
              Tool execution
            </Text>
          </View>
          <Text className="text-xs text-[#8e8e93]">
            {calls.length} call{calls.length !== 1 ? "s" : ""} ·{" "}
            {uniqueToolsCount} tool{uniqueToolsCount !== 1 ? "s" : ""}
          </Text>
        </View>

        {/* Tool call rows */}
        {calls.map((call, idx) => {
          const label =
            call.message || call.integration_name || call.tool_name || "Tool";
          const categoryLabel = getToolCategoryLabel(call);
          const key =
            call.tool_call_id ||
            call.tool_name ||
            call.integration_name ||
            `${label}-${idx}`;
          const isOpen = !!openCallIds[key];
          const hasInputs = call.inputs && Object.keys(call.inputs).length > 0;
          const hasOutput = !!call.output?.trim();
          const hasDetails = hasInputs || hasOutput;
          const isLast = idx === calls.length - 1;

          return (
            <View key={key} className="flex-row items-stretch gap-3">
              {/* Timeline spine */}
              <View className="items-center" style={{ width: 20 }}>
                <View className="w-5 h-5 rounded-md bg-white/8 items-center justify-center mt-0.5">
                  <AppIcon
                    icon={Settings01Icon}
                    size={11}
                    color="#8e8e93"
                    strokeWidth={2}
                  />
                </View>
                {!isLast && <View className="w-px flex-1 bg-white/10 mt-1" />}
              </View>

              {/* Content */}
              <View className={`flex-1 ${isLast ? "mb-0" : "mb-3"}`}>
                <Pressable
                  onPress={() => hasDetails && toggle(key)}
                  className="flex-row items-center gap-1"
                >
                  <Text className="text-sm font-medium text-foreground flex-1">
                    {label}
                  </Text>
                  {hasDetails && (
                    <AppIcon
                      icon={ArrowDown01Icon}
                      size={14}
                      color="#8e8e93"
                      strokeWidth={2}
                      style={{
                        transform: [{ rotate: isOpen ? "180deg" : "0deg" }],
                      }}
                    />
                  )}
                </Pressable>

                {!!categoryLabel && call.show_category !== false && (
                  <Text className="text-[11px] text-[#8e8e93] mt-0.5">
                    {categoryLabel}
                  </Text>
                )}

                {isOpen && hasDetails && (
                  <View className="mt-2 rounded-xl bg-black/30 p-3 gap-2">
                    {hasInputs && (
                      <View>
                        <Text className="text-[10px] text-[#8e8e93] font-medium mb-1">
                          INPUT
                        </Text>
                        <Text
                          className="text-xs text-foreground font-mono"
                          numberOfLines={8}
                        >
                          {JSON.stringify(call.inputs, null, 2)}
                        </Text>
                      </View>
                    )}
                    {hasOutput && (
                      <View>
                        <Text className="text-[10px] text-[#8e8e93] font-medium mb-1">
                          OUTPUT
                        </Text>
                        <Text
                          className="text-xs text-foreground"
                          numberOfLines={10}
                        >
                          {call.output}
                        </Text>
                      </View>
                    )}
                  </View>
                )}
              </View>
            </View>
          );
        })}
      </Card.Body>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// TwitterSearchCard
// ---------------------------------------------------------------------------

function TweetRow({ tweet }: { tweet: TwitterTweetData }) {
  const author = tweet.author;
  const metrics = tweet.public_metrics;
  const avatarLetter =
    author?.name?.[0]?.toUpperCase() ||
    author?.username?.[0]?.toUpperCase() ||
    "?";

  const handlePress = () => {
    if (tweet.id && author?.username) {
      Linking.openURL(
        `https://twitter.com/${author.username}/status/${tweet.id}`,
      );
    }
  };

  return (
    <Pressable
      onPress={handlePress}
      className="rounded-xl bg-white/5 border border-white/8 p-3 mb-2"
    >
      {/* Author row */}
      <View className="flex-row items-center gap-2 mb-2">
        <View className="w-8 h-8 rounded-full bg-primary/20 items-center justify-center shrink-0">
          <Text className="text-sm font-semibold text-primary">
            {avatarLetter}
          </Text>
        </View>
        <View className="flex-1 min-w-0">
          <View className="flex-row items-center gap-1">
            <Text
              className="text-sm font-semibold text-foreground"
              numberOfLines={1}
            >
              {author?.name || author?.username || "Unknown"}
            </Text>
            {author?.verified && (
              <AppIcon
                icon={CheckmarkCircle02Icon}
                size={13}
                color="#1d9bf0"
                strokeWidth={2}
              />
            )}
          </View>
          <View className="flex-row items-center gap-1">
            {!!author?.username && (
              <Text className="text-[11px] text-[#8e8e93]">
                @{author.username}
              </Text>
            )}
            {!!tweet.created_at && (
              <>
                <Text className="text-[11px] text-[#8e8e93]">·</Text>
                <Text className="text-[11px] text-[#8e8e93]">
                  {formatTweetDate(tweet.created_at)}
                </Text>
              </>
            )}
          </View>
        </View>
      </View>

      {/* Tweet text */}
      <Text
        className="text-sm text-foreground leading-relaxed"
        numberOfLines={4}
      >
        {tweet.text}
      </Text>

      {/* Metrics */}
      {metrics && (
        <View className="flex-row items-center gap-5 mt-2.5 pt-2 border-t border-white/8">
          <View className="flex-row items-center gap-1">
            <AppIcon
              icon={FavouriteIcon}
              size={13}
              color="#8e8e93"
              strokeWidth={2}
            />
            <Text className="text-[11px] text-[#8e8e93]">
              {formatNumber(metrics.like_count)}
            </Text>
          </View>
          <View className="flex-row items-center gap-1">
            <AppIcon
              icon={MessageMultiple01Icon}
              size={13}
              color="#8e8e93"
              strokeWidth={2}
            />
            <Text className="text-[11px] text-[#8e8e93]">
              {formatNumber(metrics.reply_count)}
            </Text>
          </View>
          <View className="flex-row items-center gap-1">
            <AppIcon
              icon={RepeatIcon}
              size={13}
              color="#8e8e93"
              strokeWidth={2}
            />
            <Text className="text-[11px] text-[#8e8e93]">
              {formatNumber(metrics.retweet_count)}
            </Text>
          </View>
          <View className="flex-row items-center gap-1">
            <AppIcon
              icon={Share08Icon}
              size={13}
              color="#8e8e93"
              strokeWidth={2}
            />
          </View>
        </View>
      )}
    </Pressable>
  );
}

export function TwitterSearchCard({ data }: { data: unknown }) {
  const payload = data as Record<string, unknown>;
  const tweets = Array.isArray(payload.tweets)
    ? (payload.tweets as TwitterTweetData[])
    : [];
  const resultCount =
    typeof payload.result_count === "number" ? payload.result_count : null;

  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-2xl bg-[#171920]">
      <Card.Body className="py-3 px-4">
        {/* Header */}
        <View className="flex-row items-center justify-between mb-3">
          <View className="flex-row items-center gap-2">
            <View className="w-5 h-5 rounded-md bg-[#1d9bf0]/15 items-center justify-center">
              <AppIcon
                icon={TwitterIcon}
                size={12}
                color="#1d9bf0"
                strokeWidth={2}
              />
            </View>
            <Text className="text-xs font-medium text-[#8e8e93]">
              Twitter search
            </Text>
          </View>
          {resultCount !== null && (
            <Text className="text-xs text-[#8e8e93]">
              {resultCount} result{resultCount !== 1 ? "s" : ""}
            </Text>
          )}
        </View>

        {tweets.length === 0 ? (
          <View className="rounded-xl bg-white/5 p-4 items-center">
            <Text className="text-sm text-[#8e8e93]">No tweets found</Text>
          </View>
        ) : (
          tweets.map((tweet, idx) => (
            <TweetRow key={tweet.id || String(idx)} tweet={tweet} />
          ))
        )}
      </Card.Body>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// TwitterUsersCard
// ---------------------------------------------------------------------------

function TwitterUserRow({ user }: { user: TwitterUserData }) {
  const metrics = user.public_metrics;
  const avatarLetter =
    user.name?.[0]?.toUpperCase() || user.username?.[0]?.toUpperCase() || "?";

  const handlePress = () => {
    if (user.username) {
      Linking.openURL(`https://twitter.com/${user.username}`);
    }
  };

  return (
    <Pressable
      onPress={handlePress}
      className="rounded-xl bg-white/5 border border-white/8 p-3 mb-2"
    >
      {/* Header */}
      <View className="flex-row items-start gap-3">
        <View className="w-10 h-10 rounded-full bg-primary/20 items-center justify-center shrink-0">
          <Text className="text-base font-bold text-primary">
            {avatarLetter}
          </Text>
        </View>
        <View className="flex-1 min-w-0">
          <View className="flex-row items-center gap-1">
            <Text
              className="text-sm font-bold text-foreground"
              numberOfLines={1}
            >
              {user.name || user.username || "Unknown"}
            </Text>
            {user.verified && (
              <AppIcon
                icon={CheckmarkCircle02Icon}
                size={13}
                color="#1d9bf0"
                strokeWidth={2}
              />
            )}
          </View>
          {!!user.username && (
            <Text className="text-xs text-[#8e8e93]">@{user.username}</Text>
          )}
        </View>
      </View>

      {/* Bio */}
      {!!user.description && (
        <Text
          className="text-xs text-foreground leading-relaxed mt-2"
          numberOfLines={3}
        >
          {user.description}
        </Text>
      )}

      {/* Meta row */}
      {(!!user.location || !!user.created_at) && (
        <View className="flex-row flex-wrap gap-3 mt-2">
          {!!user.location && (
            <Text className="text-[11px] text-[#8e8e93]">{user.location}</Text>
          )}
          {!!user.created_at && (
            <Text className="text-[11px] text-[#8e8e93]">
              Joined {formatJoinDate(user.created_at)}
            </Text>
          )}
        </View>
      )}

      {/* Stats */}
      {metrics && (
        <View className="flex-row items-center gap-4 mt-2 pt-2 border-t border-white/8">
          {typeof metrics.following_count === "number" && (
            <View className="flex-row items-center gap-1">
              <Text className="text-xs font-bold text-foreground">
                {formatNumber(metrics.following_count)}
              </Text>
              <Text className="text-xs text-[#8e8e93]">Following</Text>
            </View>
          )}
          {typeof metrics.followers_count === "number" && (
            <View className="flex-row items-center gap-1">
              <Text className="text-xs font-bold text-foreground">
                {formatNumber(metrics.followers_count)}
              </Text>
              <Text className="text-xs text-[#8e8e93]">Followers</Text>
            </View>
          )}
        </View>
      )}
    </Pressable>
  );
}

export function TwitterUsersCard({ data }: { data: unknown }) {
  const users = (Array.isArray(data) ? data : [data]) as TwitterUserData[];

  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-2xl bg-[#171920]">
      <Card.Body className="py-3 px-4">
        <View className="flex-row items-center gap-2 mb-3">
          <View className="w-5 h-5 rounded-md bg-[#1d9bf0]/15 items-center justify-center">
            <AppIcon
              icon={TwitterIcon}
              size={12}
              color="#1d9bf0"
              strokeWidth={2}
            />
          </View>
          <Text className="text-xs font-medium text-[#8e8e93]">
            Twitter users
          </Text>
          <Text className="text-xs text-[#8e8e93] ml-auto">
            {users.length} user{users.length !== 1 ? "s" : ""}
          </Text>
        </View>

        {users.length === 0 ? (
          <View className="rounded-xl bg-white/5 p-4 items-center">
            <Text className="text-sm text-[#8e8e93]">No users found</Text>
          </View>
        ) : (
          users.map((user, idx) => (
            <TwitterUserRow
              key={user.id || user.username || String(idx)}
              user={user}
            />
          ))
        )}
      </Card.Body>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// WorkflowDraftCard
// ---------------------------------------------------------------------------

export function WorkflowDraftCard({ data }: { data: unknown }) {
  const draft = data as WorkflowDraftData;

  const triggerLabel =
    draft.trigger_type === "scheduled" && draft.cron_expression
      ? draft.cron_expression
      : draft.trigger_type === "integration" && draft.trigger_slug
        ? draft.trigger_slug
            .split("_")
            .slice(0, 2)
            .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
            .join(" ")
        : undefined;

  const trigger = getTriggerInfo(draft.trigger_type, triggerLabel);

  const TriggerIcon =
    draft.trigger_type === "scheduled"
      ? Clock01Icon
      : draft.trigger_type === "integration"
        ? Calendar03Icon
        : FlashIcon;

  return (
    <Card
      variant="secondary"
      className="mx-4 my-2 rounded-2xl bg-[#171920] border border-dashed border-yellow-500/40"
    >
      <Card.Body className="py-3 px-4">
        {/* Draft badge */}
        <View className="flex-row items-center justify-between mb-3">
          <Chip variant="soft" color="warning" size="sm">
            <Chip.Label className="font-semibold">DRAFT</Chip.Label>
          </Chip>
          <Chip
            variant="soft"
            color={
              draft.trigger_type === "scheduled"
                ? "accent"
                : draft.trigger_type === "integration"
                  ? "default"
                  : "default"
            }
            size="sm"
          >
            <AppIcon
              icon={TriggerIcon}
              size={11}
              color={
                draft.trigger_type === "scheduled"
                  ? "#00bbff"
                  : draft.trigger_type === "integration"
                    ? "#c084fc"
                    : "#8e8e93"
              }
              strokeWidth={2}
            />
            <Chip.Label>{trigger.label}</Chip.Label>
          </Chip>
        </View>

        {/* Icon + Title */}
        <View className="flex-row items-start gap-3 mb-2">
          <View className="w-10 h-10 rounded-xl bg-primary/15 items-center justify-center shrink-0">
            <AppIcon
              icon={FlowIcon}
              size={20}
              color="#00bbff"
              strokeWidth={2}
            />
          </View>
          <View className="flex-1 min-w-0">
            <Text
              className="text-base font-medium text-foreground leading-tight"
              numberOfLines={2}
            >
              {draft.suggested_title || "New workflow"}
            </Text>
            <Text className="text-xs text-yellow-500/80 mt-0.5">
              Review to create workflow
            </Text>
          </View>
        </View>

        {/* Description */}
        {!!draft.suggested_description && (
          <Text
            className="text-xs text-[#8e8e93] leading-relaxed mb-3"
            numberOfLines={3}
          >
            {draft.suggested_description}
          </Text>
        )}

        {draft.trigger_type === "integration" && (
          <Text className="text-xs text-[#8e8e93] mb-3">
            Configure trigger settings to complete setup
          </Text>
        )}

        <View className="rounded-xl bg-white/5 px-3 py-2">
          <Text className="text-xs text-[#8e8e93] text-center">
            Review & create this workflow on web
          </Text>
        </View>
      </Card.Body>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// WorkflowCreatedCard
// ---------------------------------------------------------------------------

export function WorkflowCreatedCard({ data }: { data: unknown }) {
  const workflow = data as WorkflowCreatedData;
  const triggerConfig = workflow.trigger_config;

  const triggerLabel =
    triggerConfig?.type === "scheduled" && triggerConfig.cron_expression
      ? triggerConfig.cron_expression
      : triggerConfig?.type === "integration" && triggerConfig.trigger_name
        ? triggerConfig.trigger_name
            .split("_")
            .slice(0, 2)
            .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
            .join(" ")
        : undefined;

  const trigger = getTriggerInfo(triggerConfig?.type, triggerLabel);

  const TriggerIcon =
    triggerConfig?.type === "scheduled"
      ? Clock01Icon
      : triggerConfig?.type === "integration"
        ? Calendar03Icon
        : FlashIcon;

  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-2xl bg-[#171920]">
      <Card.Body className="py-3 px-4">
        {/* Header */}
        <View className="flex-row items-start justify-between gap-3 mb-2">
          <View className="flex-row items-center gap-3 flex-1 min-w-0">
            <View className="w-10 h-10 rounded-xl bg-green-500/15 items-center justify-center shrink-0">
              <AppIcon
                icon={FlowIcon}
                size={20}
                color="#22c55e"
                strokeWidth={2}
              />
            </View>
            <View className="flex-1 min-w-0">
              <Text
                className="text-base font-medium text-foreground leading-tight"
                numberOfLines={2}
              >
                {workflow.title || "Workflow"}
              </Text>
              <Text className="text-xs text-[#8e8e93] mt-0.5">
                Workflow Created
              </Text>
            </View>
          </View>

          {/* Created badge */}
          <Chip variant="soft" color="success" size="sm" className="shrink-0">
            <AppIcon
              icon={CheckmarkCircle02Icon}
              size={11}
              color="#22c55e"
              strokeWidth={2}
            />
            <Chip.Label>Created</Chip.Label>
          </Chip>
        </View>

        {/* Description */}
        {!!workflow.description && (
          <Text
            className="text-xs text-[#8e8e93] leading-relaxed mb-3"
            numberOfLines={3}
          >
            {workflow.description}
          </Text>
        )}

        {/* Trigger chip */}
        {triggerConfig?.type && (
          <Chip
            variant="soft"
            color={
              triggerConfig.type === "scheduled"
                ? "accent"
                : triggerConfig.type === "integration"
                  ? "default"
                  : "default"
            }
            size="sm"
            className="mb-3"
          >
            <AppIcon
              icon={TriggerIcon}
              size={11}
              color={
                triggerConfig.type === "scheduled"
                  ? "#00bbff"
                  : triggerConfig.type === "integration"
                    ? "#c084fc"
                    : "#8e8e93"
              }
              strokeWidth={2}
            />
            <Chip.Label>{trigger.label}</Chip.Label>
          </Chip>
        )}

        {/* Activated status */}
        <View className="flex-row items-center gap-2 rounded-xl bg-white/5 px-3 py-2">
          <View
            className={`w-2 h-2 rounded-full ${workflow.activated ? "bg-green-500" : "bg-[#8e8e93]"}`}
          />
          <Text className="text-xs text-[#8e8e93]">
            {workflow.activated ? "Active" : "Not active"} · View & edit on web
          </Text>
        </View>
      </Card.Body>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// MCPAppCard
// ---------------------------------------------------------------------------

export function MCPAppCard({ data }: { data: unknown }) {
  const app = data as Record<string, unknown>;
  const toolName =
    typeof app.tool_name === "string" ? app.tool_name : "Interactive app";
  const serverUrl = typeof app.server_url === "string" ? app.server_url : null;

  const displayName = toolName
    .split("_")
    .map((w: string) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");

  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-2xl bg-[#171920]">
      <Card.Body className="py-3 px-4">
        {/* Header */}
        <View className="flex-row items-center gap-2 mb-3">
          <View className="w-5 h-5 rounded-md bg-primary/15 items-center justify-center">
            <AppIcon icon={CpuIcon} size={12} color="#00bbff" strokeWidth={2} />
          </View>
          <Text className="text-xs font-medium text-[#8e8e93]">
            Interactive app
          </Text>
        </View>

        {/* App info */}
        <View className="flex-row items-start gap-3 mb-3">
          <View className="w-10 h-10 rounded-xl bg-primary/10 items-center justify-center shrink-0">
            <AppIcon
              icon={FlowIcon}
              size={20}
              color="#00bbff"
              strokeWidth={2}
            />
          </View>
          <View className="flex-1 min-w-0">
            <Text
              className="text-sm font-medium text-foreground"
              numberOfLines={1}
            >
              {displayName}
            </Text>
            {!!serverUrl && (
              <Text
                className="text-[11px] text-[#8e8e93] mt-0.5"
                numberOfLines={1}
              >
                {serverUrl.replace(/^https?:\/\//, "")}
              </Text>
            )}
          </View>
        </View>

        {/* Notice */}
        <View className="rounded-xl bg-white/5 border border-white/8 px-3 py-2.5">
          <View className="flex-row items-start gap-2">
            <AppIcon
              icon={Alert01Icon}
              size={14}
              color="#8e8e93"
              strokeWidth={2}
              style={{ marginTop: 1 }}
            />
            <Text className="text-xs text-[#8e8e93] flex-1 leading-relaxed">
              Interactive rendering is available on web. The result is still
              included in the conversation.
            </Text>
          </View>
        </View>
      </Card.Body>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// RateLimitCard
// ---------------------------------------------------------------------------

const PRO_BENEFITS = [
  "10× higher daily limits on all features",
  "Priority responses and faster processing",
];

export function RateLimitCard({ data }: { data: unknown }) {
  const item = data as RateLimitData;
  const featureName = formatFeatureName(item.feature);
  const resetLabel = formatResetTime(item.reset_time);
  const resetDetail = getResetDetail(item.reset_time);
  const isUpgradeRequired = !!item.plan_required;
  const planName = item.plan_required?.toUpperCase() ?? "PRO";

  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-2xl bg-[#171920]">
      <Card.Body className="p-0">
        {/* Header */}
        <View className="flex-row items-start justify-between gap-3 px-4 pt-3 pb-3">
          <View className="flex-row items-center gap-3 flex-1 min-w-0">
            <View
              className={`w-10 h-10 rounded-xl items-center justify-center shrink-0 ${
                isUpgradeRequired ? "bg-yellow-500/15" : "bg-red-500/15"
              }`}
            >
              <AppIcon
                icon={isUpgradeRequired ? UploadCircle01Icon : Clock01Icon}
                size={20}
                color={isUpgradeRequired ? "#eab308" : "#ef4444"}
                strokeWidth={2}
              />
            </View>
            <View className="flex-1 min-w-0">
              <Text className="text-sm font-semibold text-foreground leading-tight">
                {featureName}
              </Text>
              <Text className="text-xs text-[#8e8e93] mt-0.5">
                {isUpgradeRequired
                  ? `Requires ${planName} plan`
                  : "Daily limit reached"}
              </Text>
            </View>
          </View>

          <Chip
            variant="soft"
            color={isUpgradeRequired ? "warning" : "danger"}
            size="sm"
            className="shrink-0"
          >
            <Chip.Label className="font-semibold">
              {isUpgradeRequired ? planName : "Limit Hit"}
            </Chip.Label>
          </Chip>
        </View>

        {/* Divider */}
        <View className="h-px bg-white/8 mx-4" />

        {/* Body */}
        <View className="px-4 py-3 gap-3">
          {isUpgradeRequired ? (
            <>
              <Text className="text-xs text-[#8e8e93] leading-relaxed">
                <Text className="text-white font-medium">{featureName} </Text>
                is a{" "}
                <Text className="text-yellow-400 font-medium">{planName} </Text>
                feature and isn't included in your current plan. Upgrade to
                unlock it and get significantly higher limits across every
                feature.
              </Text>
              <View className="gap-1.5">
                {PRO_BENEFITS.map((benefit) => (
                  <View key={benefit} className="flex-row items-start gap-2">
                    <AppIcon
                      icon={CheckmarkCircle02Icon}
                      size={13}
                      color="#00bbff"
                      strokeWidth={2}
                      style={{ marginTop: 1 }}
                    />
                    <Text className="text-xs text-[#8e8e93] flex-1">
                      {benefit}
                    </Text>
                  </View>
                ))}
              </View>
            </>
          ) : (
            <>
              <Text className="text-xs text-[#8e8e93] leading-relaxed">
                You've used all your{" "}
                <Text className="text-white font-medium">{featureName} </Text>
                calls for today. Your limit will automatically reset — no action
                needed.
              </Text>

              {!!resetLabel && (
                <View className="flex-row items-center gap-3 rounded-xl bg-white/8 px-3 py-2.5">
                  <AppIcon
                    icon={Clock01Icon}
                    size={16}
                    color="#8e8e93"
                    strokeWidth={2}
                  />
                  <View className="flex-1">
                    <Text className="text-xs font-medium text-foreground">
                      {resetLabel}
                    </Text>
                    {!!resetDetail && (
                      <Text className="text-[11px] text-[#8e8e93] mt-0.5">
                        {resetDetail}
                      </Text>
                    )}
                  </View>
                </View>
              )}

              <View className="flex-row items-start gap-2 px-1">
                <AppIcon
                  icon={Alert01Icon}
                  size={13}
                  color="#8e8e93"
                  strokeWidth={2}
                  style={{ marginTop: 1 }}
                />
                <Text className="text-xs text-[#8e8e93] flex-1">
                  Need more? Upgrade to{" "}
                  <Text className="text-white font-medium">PRO</Text> for 10×
                  higher daily limits on {featureName} and all other features.
                </Text>
              </View>
            </>
          )}
        </View>

        {/* Divider */}
        <View className="h-px bg-white/8 mx-4" />

        {/* Footer */}
        <View className="px-4 py-3">
          <Button
            size="sm"
            variant={isUpgradeRequired ? "primary" : "secondary"}
            className="w-full rounded-xl"
            isDisabled
          >
            <Button.Label>
              {isUpgradeRequired
                ? `Upgrade to ${planName}`
                : "View Plans on Web"}
            </Button.Label>
          </Button>
        </View>
      </Card.Body>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// ArtifactCard
// ---------------------------------------------------------------------------

const EXT_ICON_MAP: Record<string, typeof CodeIcon> = {
  JS: CodeIcon,
  TS: CodeIcon,
  TSX: CodeIcon,
  JSX: CodeIcon,
  JSON: CodeIcon,
  PY: CodeIcon,
};

export function ArtifactCard({ data }: { data: unknown }) {
  const artifacts = (Array.isArray(data) ? data : [data]) as ArtifactItem[];

  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-2xl bg-[#171920]">
      <Card.Body className="py-3 px-4">
        {/* Header */}
        <View className="flex-row items-center gap-2 mb-3">
          <View className="w-5 h-5 rounded-md bg-white/10 items-center justify-center">
            <AppIcon
              icon={DocumentAttachmentIcon}
              size={12}
              color="#8e8e93"
              strokeWidth={2}
            />
          </View>
          <Text className="text-xs font-medium text-[#8e8e93]">
            Generated artifacts
          </Text>
          <Text className="text-xs text-[#8e8e93] ml-auto">
            {artifacts.length} file{artifacts.length !== 1 ? "s" : ""}
          </Text>
        </View>

        {artifacts.map((artifact, index) => {
          const extLabel = getExtLabel(
            artifact.filename,
            artifact.content_type,
          );
          const IconComp = EXT_ICON_MAP[extLabel] ?? DocumentAttachmentIcon;

          return (
            <View
              key={`${artifact.path || artifact.filename || "artifact"}-${artifact.size_bytes || 0}-${index}`}
              className={`rounded-xl bg-white/5 border border-white/8 px-3 py-3 ${
                index > 0 ? "mt-2" : ""
              }`}
            >
              <View className="flex-row items-center gap-3">
                <View className="w-9 h-9 rounded-lg bg-primary/10 items-center justify-center shrink-0">
                  <AppIcon
                    icon={IconComp}
                    size={18}
                    color="#00bbff"
                    strokeWidth={2}
                  />
                </View>
                <View className="flex-1 min-w-0">
                  <View className="flex-row items-center gap-2">
                    <Text
                      className="text-sm font-medium text-foreground flex-1"
                      numberOfLines={1}
                    >
                      {artifact.filename ||
                        artifact.path ||
                        `Artifact ${index + 1}`}
                    </Text>
                    <Chip
                      variant="soft"
                      color="accent"
                      size="sm"
                      className="shrink-0"
                    >
                      <Chip.Label className="font-medium">
                        {extLabel}
                      </Chip.Label>
                    </Chip>
                  </View>
                  <Text
                    className="text-[11px] text-[#8e8e93] mt-0.5"
                    numberOfLines={1}
                  >
                    {formatBytes(artifact.size_bytes)}
                    {artifact.content_type ? ` · ${artifact.content_type}` : ""}
                  </Text>
                </View>
              </View>
              {!!artifact.path && artifact.path !== artifact.filename && (
                <Text
                  className="text-[10px] text-[#8e8e93] mt-2 pl-12"
                  numberOfLines={1}
                >
                  {artifact.path}
                </Text>
              )}
            </View>
          );
        })}
      </Card.Body>
    </Card>
  );
}
