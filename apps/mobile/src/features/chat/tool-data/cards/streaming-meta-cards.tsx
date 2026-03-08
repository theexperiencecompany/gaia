import { Card } from "heroui-native";
import { View } from "react-native";
import { Text } from "@/components/ui/text";

interface ToolCallEntry {
  tool_call_id?: string;
  tool_name?: string;
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

export function ToolCallsCard({ data }: { data: unknown }) {
  const calls = (Array.isArray(data) ? data : [data]) as ToolCallEntry[];
  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-xl">
      <Card.Body className="py-3 px-4">
        <Text className="text-xs text-muted mb-2">Tool execution</Text>
        {calls.map((call) => {
          const label = call.integration_name || call.tool_name || "Tool";
          const key =
            call.tool_call_id ||
            call.tool_name ||
            call.integration_name ||
            `${label}-${call.message || "pending"}`;
          return (
            <View key={key} className="mb-2">
              <Text className="text-sm text-foreground font-medium">
                {label}
              </Text>
              {!!call.message && (
                <Text className="text-xs text-muted">{call.message}</Text>
              )}
              {!!call.output && (
                <Text
                  className="text-xs text-foreground mt-1"
                  numberOfLines={4}
                >
                  {call.output}
                </Text>
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
    <Card variant="secondary" className="mx-4 my-2 rounded-xl">
      <Card.Body className="py-3 px-4">
        <Text className="text-xs text-muted mb-2">Generated artifacts</Text>
        {artifacts.map((artifact, index) => (
          <View
            key={`${artifact.path || artifact.filename || "artifact"}-${artifact.size_bytes || 0}`}
            className={index > 0 ? "mt-2" : ""}
          >
            <Text className="text-sm text-foreground font-medium">
              {artifact.filename || artifact.path || `Artifact ${index + 1}`}
            </Text>
            <Text className="text-xs text-muted" numberOfLines={1}>
              {formatBytes(artifact.size_bytes)}
              {artifact.content_type ? ` • ${artifact.content_type}` : ""}
            </Text>
          </View>
        ))}
      </Card.Body>
    </Card>
  );
}

export function RateLimitCard({ data }: { data: unknown }) {
  const item = data as RateLimitData;

  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-xl">
      <Card.Body className="py-3 px-4">
        <Text className="text-xs text-muted">Usage limit</Text>
        <Text className="text-sm text-foreground mt-1">
          {item.feature || "Feature"}
        </Text>
        {!!item.plan_required && (
          <Text className="text-xs text-warning mt-1">
            Requires {item.plan_required} plan
          </Text>
        )}
        {!!item.reset_time && (
          <Text className="text-xs text-muted mt-1">
            Resets at {item.reset_time}
          </Text>
        )}
      </Card.Body>
    </Card>
  );
}

export function WorkflowDraftCard({ data }: { data: unknown }) {
  const draft = data as WorkflowDraftData;
  return (
    <Card variant="secondary" className="mx-4 my-2 rounded-xl">
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
    <Card variant="secondary" className="mx-4 my-2 rounded-xl">
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
    <Card variant="secondary" className="mx-4 my-2 rounded-xl">
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
    <Card variant="secondary" className="mx-4 my-2 rounded-xl">
      <Card.Body className="py-3 px-4">
        <Text className="text-xs text-muted mb-2">Twitter users</Text>
        {users.map((user, index) => (
          <View key={`${user.username || user.name || "user"}-${index}`}>
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
    <Card variant="secondary" className="mx-4 my-2 rounded-xl">
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
