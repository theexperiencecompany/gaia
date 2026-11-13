import * as Haptics from "expo-haptics";
import { useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { Pressable, View } from "react-native";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { AppStatusChip } from "@/shared/components/ui/app-status-chip";
import { WORKFLOW_COLORS } from "../constants/colors";
import { ACTIVATION_STATUS } from "../constants/status";
import type { Workflow } from "../types/workflow-types";
import { WorkflowCardMetaRow } from "./workflow-card-meta-row";
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

  const activation =
    ACTIVATION_STATUS[optimistic.activated ? "activated" : "deactivated"];

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

        <AppStatusChip
          status={activation.chipStatus}
          label={activation.label}
        />
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

      <WorkflowCardMetaRow workflow={optimistic} />
    </Pressable>
  );
}
