import { View } from "react-native";
import { AppIcon, Clock04Icon, PlayIcon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { AppStatusChip } from "@/shared/components/ui/app-status-chip";
import { WORKFLOW_COLORS } from "../constants/colors";
import type { Workflow } from "../types/workflow-types";
import { formatRunCount, getTriggerLabel } from "../utils/format-utils";

interface WorkflowCardMetaRowProps {
  workflow: Workflow;
}

/**
 * One tight meta line under the card title: trigger summary and run count
 * side-by-side (each hidden when it carries no information), plus a "System"
 * chip at the trailing edge. Renders nothing when there is nothing to say.
 */
export function WorkflowCardMetaRow({ workflow }: WorkflowCardMetaRowProps) {
  const { fontSize } = useResponsive();

  const triggerLabel = getTriggerLabel(
    workflow.trigger_config?.type ?? "manual",
  );
  const runCountText = formatRunCount(workflow.total_executions ?? 0);

  const showTrigger = triggerLabel !== "Manual";
  const showRunCount = runCountText !== "Never run";
  const hasMeta = showTrigger || showRunCount;

  if (!hasMeta && !workflow.is_system_workflow) return null;

  return (
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

      {workflow.is_system_workflow ? (
        <AppStatusChip tone="accent" label="System" />
      ) : null}
    </View>
  );
}
