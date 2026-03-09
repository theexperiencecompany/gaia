import { ActivityIndicator, View } from "react-native";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import type { WorkflowExecution } from "../types/workflow-types";

interface WorkflowExecutionHistoryProps {
  executions: WorkflowExecution[];
  isLoading: boolean;
}

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function statusColor(status: WorkflowExecution["status"]): string {
  if (status === "success") return "#22c55e";
  if (status === "running") return "#f59e0b";
  return "#ef4444";
}

export function WorkflowExecutionHistory({
  executions,
  isLoading,
}: WorkflowExecutionHistoryProps) {
  const { spacing, fontSize, moderateScale } = useResponsive();

  if (isLoading) {
    return (
      <View style={{ paddingVertical: spacing.lg, alignItems: "center" }}>
        <ActivityIndicator size="small" color="#16c1ff" />
      </View>
    );
  }

  if (executions.length === 0) {
    return (
      <View style={{ paddingVertical: spacing.lg, alignItems: "center" }}>
        <Text style={{ fontSize: fontSize.xs, color: "#555" }}>
          No executions yet
        </Text>
      </View>
    );
  }

  return (
    <View style={{ gap: spacing.sm }}>
      {executions.map((execution) => (
        <View
          key={execution.execution_id}
          style={{
            borderRadius: moderateScale(12, 0.5),
            borderWidth: 1,
            borderColor: "rgba(255,255,255,0.07)",
            backgroundColor: "#111318",
            padding: spacing.md,
            gap: spacing.xs,
          }}
        >
          <View
            style={{
              flexDirection: "row",
              alignItems: "center",
              gap: spacing.sm,
            }}
          >
            <View
              style={{
                width: 8,
                height: 8,
                borderRadius: 999,
                backgroundColor: statusColor(execution.status),
              }}
            />
            <Text
              style={{
                fontSize: fontSize.xs,
                color: statusColor(execution.status),
                textTransform: "capitalize",
              }}
            >
              {execution.status}
            </Text>
            <View style={{ flex: 1 }} />
            <Text style={{ fontSize: fontSize.xs - 1, color: "#555" }}>
              {formatDate(execution.started_at)}
            </Text>
          </View>

          {execution.summary ? (
            <Text
              style={{ fontSize: fontSize.xs, color: "#8a9099" }}
              numberOfLines={2}
            >
              {execution.summary}
            </Text>
          ) : null}

          {execution.duration_seconds !== undefined && (
            <Text style={{ fontSize: fontSize.xs - 1, color: "#444" }}>
              {execution.duration_seconds.toFixed(1)}s
            </Text>
          )}
        </View>
      ))}
    </View>
  );
}
