import { useRouter } from "expo-router";
import { ActivityIndicator, Pressable, View } from "react-native";
import {
  AlertCircleIcon,
  AppIcon,
  ArrowRight01Icon,
  CheckmarkCircle02Icon,
  Clock04Icon,
  Loading03Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import type { WorkflowExecution } from "../types/workflow-types";
import { formatDuration, formatRelativeDate } from "../utils/format-utils";

interface WorkflowExecutionHistoryProps {
  executions: WorkflowExecution[];
  isLoading: boolean;
  hasMore?: boolean;
  total?: number;
  onLoadMore?: () => void;
}

function statusColor(status: WorkflowExecution["status"]): string {
  if (status === "success") return "#22c55e";
  if (status === "running") return "#f59e0b";
  return "#ef4444";
}

function statusBgColor(status: WorkflowExecution["status"]): string {
  if (status === "success") return "rgba(34,197,94,0.12)";
  if (status === "running") return "rgba(245,158,11,0.12)";
  return "rgba(239,68,68,0.12)";
}

function StatusIcon({ status }: { status: WorkflowExecution["status"] }) {
  if (status === "success") {
    return <AppIcon icon={CheckmarkCircle02Icon} size={12} color="#22c55e" />;
  }
  if (status === "running") {
    return <AppIcon icon={Loading03Icon} size={12} color="#f59e0b" />;
  }
  return <AppIcon icon={AlertCircleIcon} size={12} color="#ef4444" />;
}

function ExecutionItem({ execution }: { execution: WorkflowExecution }) {
  const router = useRouter();
  const { spacing, fontSize, moderateScale } = useResponsive();
  const isClickable = !!execution.conversation_id;
  const durationText = formatDuration(execution.duration_seconds);
  const relativeDate = formatRelativeDate(execution.started_at);

  const handlePress = () => {
    if (execution.conversation_id) {
      router.push(`/(app)/c/${execution.conversation_id}`);
    }
  };

  return (
    <Pressable
      onPress={isClickable ? handlePress : undefined}
      style={({ pressed }) => ({
        borderRadius: moderateScale(12, 0.5),
        backgroundColor:
          pressed && isClickable ? "rgba(63,63,70,0.6)" : "rgba(39,39,42,0.5)",
        padding: spacing.md,
        gap: spacing.xs,
      })}
    >
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
          {/* Status badge */}
          <View
            style={{
              flexDirection: "row",
              alignItems: "center",
              gap: 4,
              borderRadius: 6,
              paddingHorizontal: 7,
              paddingVertical: 3,
              backgroundColor: statusBgColor(execution.status),
            }}
          >
            <StatusIcon status={execution.status} />
            <Text
              style={{
                fontSize: fontSize.xs - 1,
                color: statusColor(execution.status),
                textTransform: "capitalize",
              }}
            >
              {execution.status === "success"
                ? "Success"
                : execution.status === "running"
                  ? "Running"
                  : "Failed"}
            </Text>
          </View>

          {/* Duration */}
          {durationText ? (
            <Text style={{ fontSize: fontSize.xs - 1, color: "#71717a" }}>
              {durationText}
            </Text>
          ) : null}
        </View>

        <View style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
          <Text style={{ fontSize: fontSize.xs - 1, color: "#71717a" }}>
            {relativeDate}
          </Text>
          {isClickable && (
            <AppIcon icon={ArrowRight01Icon} size={14} color="#71717a" />
          )}
        </View>
      </View>

      {execution.summary ? (
        <Text
          style={{ fontSize: fontSize.xs, color: "#8a9099", lineHeight: 16 }}
          numberOfLines={2}
        >
          {execution.summary}
        </Text>
      ) : null}

      {execution.error_message ? (
        <Text
          style={{ fontSize: fontSize.xs, color: "#ef4444" }}
          numberOfLines={2}
        >
          {execution.error_message}
        </Text>
      ) : null}
    </Pressable>
  );
}

export function WorkflowExecutionHistory({
  executions,
  isLoading,
  hasMore,
  total,
  onLoadMore,
}: WorkflowExecutionHistoryProps) {
  const { spacing, fontSize, moderateScale } = useResponsive();

  if (isLoading && executions.length === 0) {
    return (
      <View style={{ gap: spacing.sm }}>
        {[1, 2, 3].map((i) => (
          <View
            key={i}
            style={{
              borderRadius: moderateScale(12, 0.5),
              backgroundColor: "rgba(39,39,42,0.5)",
              height: 56,
            }}
          />
        ))}
      </View>
    );
  }

  if (executions.length === 0) {
    return (
      <View
        style={{
          paddingVertical: spacing.xl,
          alignItems: "center",
          gap: spacing.sm,
        }}
      >
        <View
          style={{
            width: 40,
            height: 40,
            borderRadius: 999,
            backgroundColor: "rgba(39,39,42,0.5)",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <AppIcon icon={Clock04Icon} size={18} color="#71717a" />
        </View>
        <Text style={{ fontSize: fontSize.sm, color: "#71717a" }}>
          No executions yet
        </Text>
        <Text style={{ fontSize: fontSize.xs, color: "#555" }}>
          Run this workflow to see execution history
        </Text>
      </View>
    );
  }

  return (
    <View style={{ gap: spacing.sm }}>
      {/* Count badge row */}
      {total !== undefined && total > 0 && (
        <View style={{ flexDirection: "row", alignItems: "center" }}>
          <View
            style={{
              borderRadius: 999,
              backgroundColor: "rgba(39,39,42,1)",
              paddingHorizontal: 10,
              paddingVertical: 3,
            }}
          >
            <Text
              style={{
                fontSize: fontSize.xs,
                fontWeight: "500",
                color: "#a1a1aa",
              }}
            >
              {total} runs
            </Text>
          </View>
        </View>
      )}

      {executions.map((execution) => (
        <ExecutionItem key={execution.execution_id} execution={execution} />
      ))}

      {hasMore && onLoadMore && (
        <Pressable
          onPress={onLoadMore}
          style={({ pressed }) => ({
            borderRadius: moderateScale(12, 0.5),
            paddingVertical: spacing.md,
            alignItems: "center",
            backgroundColor: pressed
              ? "rgba(63,63,70,0.5)"
              : "rgba(39,39,42,0.4)",
          })}
        >
          {isLoading ? (
            <ActivityIndicator size="small" color="#00bbff" />
          ) : (
            <Text style={{ fontSize: fontSize.sm, color: "#00bbff" }}>
              Load More
            </Text>
          )}
        </Pressable>
      )}
    </View>
  );
}
