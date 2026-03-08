import { Button, Card } from "heroui-native";
import { useMemo, useState } from "react";
import { Pressable, View } from "react-native";
import { Text } from "@/components/ui/text";

interface ToolCallEntry {
  tool_call_id?: string;
  tool_name?: string;
  tool_category?: string;
  inputs?: Record<string, unknown>;
  message?: string;
  output?: string;
  integration_name?: string;
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
}

interface WorkflowCreatedData {
  title?: string;
  description?: string;
  activated?: boolean;
}

interface TwitterUserData {
  username?: string;
  name?: string;
  followers_count?: number;
}

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
        <View className="flex-row items-center justify-between mb-2">
          <Text className="text-xs text-muted">Tool execution</Text>
          <Text className="text-xs text-muted">
            {calls.length} call{calls.length > 1 ? "s" : ""} •{" "}
            {uniqueToolsCount} tool
            {uniqueToolsCount > 1 ? "s" : ""}
          </Text>
        </View>
        {calls.map((call) => {
          const label = call.integration_name || call.tool_name || "Tool";
          const key =
            call.tool_call_id ||
            call.tool_name ||
            call.integration_name ||
            `${label}-${call.message || "pending"}`;
          const isOpen = !!openCallIds[key];
          const hasDetails = !!call.output || !!call.inputs;

          return (
            <View
              key={key}
              className="mb-2 rounded-xl bg-white/5 border border-white/8"
            >
              <Pressable
                onPress={() => hasDetails && toggle(key)}
                className="px-3 py-2.5"
              >
                <View className="flex-row items-center justify-between gap-3">
                  <View className="flex-1">
                    <Text className="text-sm text-foreground font-medium">
                      {label}
                    </Text>
                    {!!call.message && (
                      <Text className="text-xs text-muted mt-0.5">
                        {call.message}
                      </Text>
                    )}
                  </View>
                  {hasDetails && (
                    <Text className="text-xs text-primary">
                      {isOpen ? "Hide" : "View"}
                    </Text>
                  )}
                </View>
              </Pressable>

              {isOpen && hasDetails && (
                <View className="px-3 pb-3">
                  {!!call.inputs && (
                    <View className="rounded-lg bg-black/25 p-2.5 mb-2">
                      <Text className="text-[10px] text-muted mb-1">Input</Text>
                      <Text
                        className="text-xs text-foreground"
                        numberOfLines={6}
                      >
                        {JSON.stringify(call.inputs, null, 2)}
                      </Text>
                    </View>
                  )}
                  {!!call.output && (
                    <View className="rounded-lg bg-black/25 p-2.5">
                      <Text className="text-[10px] text-muted mb-1">
                        Output
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
          );
        })}
      </Card.Body>
    </Card>
  );
}

export function ArtifactCard({ data }: { data: unknown }) {
  const artifacts = (Array.isArray(data) ? data : [data]) as ArtifactItem[];

  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-2xl bg-[#171920]">
      <Card.Body className="py-3 px-4">
        <Text className="text-xs text-muted mb-2">Generated artifacts</Text>
        {artifacts.map((artifact, index) => (
          <View
            key={`${artifact.path || artifact.filename || "artifact"}-${artifact.size_bytes || 0}`}
            className={`rounded-xl bg-white/5 border border-white/8 px-3 py-2.5 ${
              index > 0 ? "mt-2" : ""
            }`}
          >
            <View className="flex-row items-center justify-between gap-2">
              <Text
                className="text-sm text-foreground font-medium flex-1"
                numberOfLines={1}
              >
                {artifact.filename || artifact.path || `Artifact ${index + 1}`}
              </Text>
              <View className="rounded-full bg-primary/20 px-2 py-0.5">
                <Text className="text-[10px] text-primary">
                  {getExtLabel(artifact.filename, artifact.content_type)}
                </Text>
              </View>
            </View>
            <Text className="text-xs text-muted mt-1" numberOfLines={1}>
              {formatBytes(artifact.size_bytes)}
              {artifact.content_type ? ` • ${artifact.content_type}` : ""}
            </Text>
            {!!artifact.path && (
              <Text className="text-[10px] text-muted mt-1" numberOfLines={1}>
                {artifact.path}
              </Text>
            )}
          </View>
        ))}
      </Card.Body>
    </Card>
  );
}

export function RateLimitCard({ data }: { data: unknown }) {
  const item = data as RateLimitData;
  const featureName = formatFeatureName(item.feature);
  const resetLabel = formatResetTime(item.reset_time);
  const isUpgradeRequired = !!item.plan_required;

  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-2xl bg-[#171920]">
      <Card.Body className="py-3 px-4">
        <View className="flex-row items-start justify-between">
          <View className="flex-1">
            <Text className="text-xs text-muted">Usage limit</Text>
            <Text className="text-sm text-foreground font-medium mt-1">
              {featureName}
            </Text>
            <Text className="text-xs text-muted mt-1">
              {isUpgradeRequired
                ? `Requires ${item.plan_required?.toUpperCase()} plan`
                : "Daily limit reached"}
            </Text>
          </View>
          <View
            className={`rounded-full px-2 py-1 ${
              isUpgradeRequired ? "bg-warning/20" : "bg-danger/20"
            }`}
          >
            <Text className="text-[10px] text-white font-semibold">
              {isUpgradeRequired ? item.plan_required?.toUpperCase() : "LIMIT"}
            </Text>
          </View>
        </View>

        <View className="rounded-xl bg-black/20 p-3 mt-3">
          {isUpgradeRequired ? (
            <Text className="text-xs text-muted">
              Upgrade to unlock {featureName} and increase limits across all
              tools.
            </Text>
          ) : (
            <Text className="text-xs text-muted">
              You have reached your daily allowance. It refreshes automatically.
            </Text>
          )}
          {!!resetLabel && (
            <Text className="text-xs text-foreground mt-2">{resetLabel}</Text>
          )}
        </View>

        <Button
          size="sm"
          variant={isUpgradeRequired ? "primary" : "secondary"}
          className="mt-3"
          isDisabled
        >
          <Button.Label>
            {isUpgradeRequired ? "Upgrade on web" : "View plans on web"}
          </Button.Label>
        </Button>
      </Card.Body>
    </Card>
  );
}

export function WorkflowDraftCard({ data }: { data: unknown }) {
  const draft = data as WorkflowDraftData;
  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-2xl bg-[#171920]">
      <Card.Body className="py-3 px-4">
        <Text className="text-xs text-muted">Workflow draft</Text>
        <Text className="text-sm text-foreground font-medium mt-1">
          {draft.suggested_title || "New workflow"}
        </Text>
        {!!draft.suggested_description && (
          <Text className="text-xs text-muted mt-1">
            {draft.suggested_description}
          </Text>
        )}
        {!!draft.trigger_type && (
          <Text className="text-xs text-primary mt-1">
            Trigger: {draft.trigger_type}
          </Text>
        )}
      </Card.Body>
    </Card>
  );
}

export function WorkflowCreatedCard({ data }: { data: unknown }) {
  const workflow = data as WorkflowCreatedData;
  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-2xl bg-[#171920]">
      <Card.Body className="py-3 px-4">
        <Text className="text-xs text-muted">Workflow created</Text>
        <Text className="text-sm text-foreground font-medium mt-1">
          {workflow.title || "Workflow"}
        </Text>
        {!!workflow.description && (
          <Text className="text-xs text-muted mt-1">
            {workflow.description}
          </Text>
        )}
        <Text className="text-xs mt-1">
          {workflow.activated ? "Active" : "Not active"}
        </Text>
      </Card.Body>
    </Card>
  );
}

export function TwitterSearchCard({ data }: { data: unknown }) {
  const payload = data as Record<string, unknown>;
  const items =
    Array.isArray(payload.tweets) && payload.tweets.length > 0
      ? payload.tweets
      : [];

  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-2xl bg-[#171920]">
      <Card.Body className="py-3 px-4">
        <Text className="text-xs text-muted">Twitter search</Text>
        {items.length === 0 ? (
          <Text className="text-xs text-muted mt-1">No results</Text>
        ) : (
          <Text className="text-xs text-foreground mt-1">
            {items.length} results
          </Text>
        )}
      </Card.Body>
    </Card>
  );
}

export function TwitterUsersCard({ data }: { data: unknown }) {
  const users = (Array.isArray(data) ? data : [data]) as TwitterUserData[];

  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-2xl bg-[#171920]">
      <Card.Body className="py-3 px-4">
        <Text className="text-xs text-muted mb-2">Twitter users</Text>
        {users.map((user) => (
          <View
            key={`${user.username || user.name || "user"}-${user.followers_count || 0}`}
          >
            <Text className="text-sm text-foreground font-medium">
              {user.name || user.username || "User"}
            </Text>
            {!!user.username && (
              <Text className="text-xs text-muted">@{user.username}</Text>
            )}
            {typeof user.followers_count === "number" && (
              <Text className="text-xs text-muted">
                {user.followers_count} followers
              </Text>
            )}
          </View>
        ))}
      </Card.Body>
    </Card>
  );
}

export function MCPAppCard({ data }: { data: unknown }) {
  const app = data as Record<string, unknown>;
  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-2xl bg-[#171920]">
      <Card.Body className="py-3 px-4">
        <Text className="text-xs text-muted">Interactive app</Text>
        <Text className="text-sm text-foreground mt-1">
          {typeof app.tool_name === "string" ? app.tool_name : "MCP app"}
        </Text>
        <Text className="text-xs text-muted mt-1">
          Interactive rendering is available on web. Result is still included in
          chat history.
        </Text>
      </Card.Body>
    </Card>
  );
}
