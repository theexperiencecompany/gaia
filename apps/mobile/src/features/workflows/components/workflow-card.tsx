import * as Haptics from "expo-haptics";
import { useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { Pressable, View } from "react-native";
import { AppIcon, Clock04Icon, PlayIcon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { AppStatusChip } from "@/shared/components/ui/app-status-chip";
import { WORKFLOW_COLORS } from "../constants/colors";
import { ACTIVATION_STATUS, EXECUTION_STATUS } from "../constants/status";
import { useWorkflowPolling } from "../hooks/use-workflow-polling";
import type { Workflow } from "../types/workflow-types";
import { formatRunCount, getTriggerLabel } from "../utils/format-utils";
import { WorkflowStepIcons } from "./workflow-step-icons";

interface WorkflowCardProps {
  workflow: Workflow;
  onPress?: (workflow: Workflow) => void;
  onUpdated?: () => void;
}

/**
 * Compact workflow row.
 *
 * Linear-style: tools + status pill in the header row, title + (optional)
 * description below, and one tight meta line that combines trigger summary
 * and run count side-by-side. Card-level overflow lives in detail — the row
 * itself stays clean (no cog icon, no inline action menu).
 */
export function WorkflowCard({ workflow, onPress }: WorkflowCardProps) {
  const router = useRouter();
  const { spacing, fontSize, moderateScale } = useResponsive();
  const [optimistic, setOptimistic] = useState<Workflow>(workflow);
  const polling = useWorkflowPolling();

  // Sync prop into local state when the parent re-fetches the row. We only
  // hard-replace when the id changes; otherwise the optimistic snapshot is
  // the source of truth until the next mutation completes.
  useEffect(() => {
    if (workflow.id !== optimistic.id) {
      setOptimistic(workflow);
    }
  }, [workflow, optimistic.id]);

  const handlePress = () => {
    void Haptics.selectionAsync();
    if (onPress) {
      onPress(workflow);
    } else {
      router.push(`/(app)/workflows/${workflow.id}`);
    }
  };

  const triggerLabel = getTriggerLabel(
    optimistic.trigger_config?.type ?? "manual",
  );
  const runCountText = formatRunCount(optimistic.total_executions ?? 0);
  const activation =
    ACTIVATION_STATUS[optimistic.activated ? "activated" : "deactivated"];

  const showTrigger = triggerLabel !== "Manual";
  const showRunCount = runCountText !== "Never run";
  const hasMeta = showTrigger || showRunCount;

  return (
    <Pressable
      onPress={handlePress}
      style={({ pressed }) => ({
        borderRadius: moderateScale(16, 0.5),
        backgroundColor: pressed
          ? WORKFLOW_COLORS.cardBgActive
          : WORKFLOW_COLORS.cardBg,
        padding: spacing.md,
        gap: spacing.sm,
      })}
    >
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        <WorkflowStepIcons steps={optimistic.steps} />

        <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
          {polling.status !== "idle" ? (
            <AppStatusChip
              status={EXECUTION_STATUS[polling.status].chipStatus}
              label={EXECUTION_STATUS[polling.status].label}
            />
          ) : null}
          <AppStatusChip
            status={activation.chipStatus}
            label={activation.label}
          />
        </View>
      </View>

      <View>
        <Text
          style={{
            fontSize: fontSize.base,
            fontWeight: "500",
            color: WORKFLOW_COLORS.textPrimary,
          }}
          numberOfLines={2}
        >
          {optimistic.title}
        </Text>
        {optimistic.description ? (
          <Text
            style={{
              fontSize: fontSize.xs,
              color: WORKFLOW_COLORS.textZinc500,
              marginTop: 4,
              lineHeight: 16,
            }}
            numberOfLines={2}
          >
            {optimistic.description}
          </Text>
        ) : null}
      </View>

      {hasMeta || optimistic.is_system_workflow ? (
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            justifyContent: "space-between",
            marginTop: 2,
          }}
        >
          <View
            style={{
              flex: 1,
              flexDirection: "row",
              alignItems: "center",
              gap: 6,
            }}
          >
            {showTrigger ? (
              <View
                style={{
                  flexDirection: "row",
                  alignItems: "center",
                  gap: 4,
                  flexShrink: 1,
                }}
              >
                <AppIcon
                  icon={Clock04Icon}
                  size={12}
                  color={WORKFLOW_COLORS.textZinc500}
                />
                <Text
                  style={{
                    fontSize: fontSize.xs,
                    color: WORKFLOW_COLORS.textZinc500,
                  }}
                  numberOfLines={1}
                >
                  {triggerLabel}
                </Text>
              </View>
            ) : null}

            {showTrigger && showRunCount ? (
              <View
                style={{
                  width: 2,
                  height: 2,
                  borderRadius: 1,
                  backgroundColor: WORKFLOW_COLORS.textZinc600,
                }}
              />
            ) : null}

            {showRunCount ? (
              <View
                style={{
                  flexDirection: "row",
                  alignItems: "center",
                  gap: 4,
                  flexShrink: 0,
                }}
              >
                <AppIcon
                  icon={PlayIcon}
                  size={12}
                  color={WORKFLOW_COLORS.textZinc500}
                />
                <Text
                  style={{
                    fontSize: fontSize.xs,
                    color: WORKFLOW_COLORS.textZinc500,
                  }}
                  numberOfLines={1}
                >
                  {runCountText}
                </Text>
              </View>
            ) : null}
          </View>

          {optimistic.is_system_workflow ? (
            <AppStatusChip tone="accent" label="System" />
          ) : null}
        </View>
      ) : null}
    </Pressable>
  );
}
