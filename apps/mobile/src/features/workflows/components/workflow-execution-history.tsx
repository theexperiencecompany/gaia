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
import { AppEmptyStateCard } from "@/shared/components/ui/app-empty-state-card";
import { AppStatusChip } from "@/shared/components/ui/app-status-chip";
import { WORKFLOW_COLORS } from "../constants/colors";
import { EXECUTION_STATUS } from "../constants/status";
import type { WorkflowExecution } from "../types/workflow-types";
import { formatDuration, formatRelativeDate } from "../utils/format-utils";

interface WorkflowExecutionHistoryProps {
  executions: WorkflowExecution[];
  isLoading: boolean;
  hasMore?: boolean;
  total?: number;
  onLoadMore?: () => void;
}

function StatusIcon({ status }: { status: WorkflowExecution["status"] }) {
  if (status === "success") {
    return (
      <AppIcon
        icon={CheckmarkCircle02Icon}
        size={11}
        color={WORKFLOW_COLORS.successText}
      />
    );
  }
  if (status === "running") {
    return (
      <AppIcon icon={Loading03Icon} size={11} color={WORKFLOW_COLORS.primary} />
    );
  }
  return (
    <AppIcon
      icon={AlertCircleIcon}
      size={11}
      color={WORKFLOW_COLORS.dangerText}
    />
  );
}

function MetaDot() {
  return (
    <View
      style={{
        width: 2,
        height: 2,
        borderRadius: 1,
        backgroundColor: WORKFLOW_COLORS.textZinc500,
      }}
    />
  );
}

function ExecutionItem({ execution }: { execution: WorkflowExecution }) {
  const router = useRouter();
  const { spacing, fontSize, moderateScale } = useResponsive();
  const isClickable = !!execution.conversation_id;
  const durationText = formatDuration(execution.duration_seconds);
  const relativeDate = formatRelativeDate(execution.started_at);
  const descriptor = EXECUTION_STATUS[execution.status];

  const handlePress = () => {
    if (execution.conversation_id) {
      router.push(`/(app)/c/${execution.conversation_id}`);
    }
  };

  return (
    <Pressable
      onPress={isClickable ? handlePress : undefined}
      style={({ pressed }) => ({
        borderRadius: moderateScale(16, 0.5),
        backgroundColor:
          pressed && isClickable
            ? WORKFLOW_COLORS.cardBgActive
            : WORKFLOW_COLORS.cardBg,
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
        <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
          <AppStatusChip
            status={descriptor.chipStatus}
            label={descriptor.label}
            startContent={<StatusIcon status={execution.status} />}
          />
          {durationText ? (
            <>
              <MetaDot />
              <Text
                style={{
                  fontSize: fontSize.xs - 1,
                  color: WORKFLOW_COLORS.textZinc500,
                }}
              >
                {durationText}
              </Text>
            </>
          ) : null}
        </View>

        <View style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
          <Text
            style={{
              fontSize: fontSize.xs - 1,
              color: WORKFLOW_COLORS.textZinc500,
            }}
          >
            {relativeDate}
          </Text>
          {isClickable ? (
            <AppIcon
              icon={ArrowRight01Icon}
              size={14}
              color={WORKFLOW_COLORS.textZinc500}
            />
          ) : null}
        </View>
      </View>

      {execution.summary ? (
        <Text
          style={{
            fontSize: fontSize.xs,
            color: WORKFLOW_COLORS.textBody,
            lineHeight: 16,
          }}
          numberOfLines={2}
        >
          {execution.summary}
        </Text>
      ) : null}

      {execution.error_message ? (
        <Text
          style={{ fontSize: fontSize.xs, color: WORKFLOW_COLORS.dangerText }}
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
              borderRadius: moderateScale(16, 0.5),
              backgroundColor: WORKFLOW_COLORS.cardBg,
              height: 56,
            }}
          />
        ))}
      </View>
    );
  }

  if (executions.length === 0) {
    return (
      <AppEmptyStateCard
        title="No executions yet"
        description="Run this workflow to see execution history."
        icon={
          <AppIcon
            icon={Clock04Icon}
            size={28}
            color={WORKFLOW_COLORS.textZinc500}
          />
        }
        className="rounded-2xl bg-zinc-800/30"
      />
    );
  }

  return (
    <View style={{ gap: spacing.sm }}>
      {total !== undefined && total > 0 ? (
        <View style={{ flexDirection: "row", alignItems: "center" }}>
          <View
            style={{
              borderRadius: 999,
              backgroundColor: WORKFLOW_COLORS.cardBgActive,
              paddingHorizontal: 10,
              paddingVertical: 3,
            }}
          >
            <Text
              style={{
                fontSize: fontSize.xs,
                fontWeight: "500",
                color: WORKFLOW_COLORS.textMuted,
              }}
            >
              {total} runs
            </Text>
          </View>
        </View>
      ) : null}

      {executions.map((execution) => (
        <ExecutionItem key={execution.execution_id} execution={execution} />
      ))}

      {hasMore && onLoadMore ? (
        <Pressable
          onPress={onLoadMore}
          style={({ pressed }) => ({
            borderRadius: moderateScale(16, 0.5),
            paddingVertical: spacing.md,
            alignItems: "center",
            backgroundColor: pressed
              ? WORKFLOW_COLORS.cardBgActive
              : WORKFLOW_COLORS.cardBg,
          })}
        >
          {isLoading ? (
            <ActivityIndicator size="small" color={WORKFLOW_COLORS.primary} />
          ) : (
            <Text
              style={{
                fontSize: fontSize.sm,
                color: WORKFLOW_COLORS.primary,
                fontWeight: "600",
              }}
            >
              Load More
            </Text>
          )}
        </Pressable>
      ) : null}
    </View>
  );
}
