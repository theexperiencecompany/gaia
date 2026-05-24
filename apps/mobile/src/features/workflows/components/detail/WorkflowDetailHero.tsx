import { View } from "react-native";
import {
  AppIcon,
  FlowCircleIcon,
  GlobeIcon,
  ZapIcon,
} from "@/components/icons";
import { useResponsive } from "@/lib/responsive";
import { AppStatusChip } from "@/shared/components/ui/app-status-chip";
import { WORKFLOW_COLORS } from "../../constants/colors";
import {
  ACTIVATION_STATUS,
  type ActivationStatus,
} from "../../constants/status";
import type { Workflow } from "../../types/workflow-types";

interface WorkflowDetailHeroProps {
  workflow: Workflow;
}

function activationKey(activated: boolean): ActivationStatus {
  return activated ? "activated" : "deactivated";
}

/**
 * Single hero card. Surfaces only what the header cannot:
 * a glyph + the status / trigger / visibility chips. Title lives in
 * the header; description / prompt lives in its own card below — we
 * never render either of them here so each piece of info appears once.
 */
export function WorkflowDetailHero({ workflow }: WorkflowDetailHeroProps) {
  const { spacing, moderateScale } = useResponsive();
  const activation = ACTIVATION_STATUS[activationKey(workflow.activated)];
  const triggerLabel = workflow.trigger_config?.type ?? "manual";

  return (
    <View
      style={{
        borderRadius: moderateScale(16, 0.5),
        backgroundColor: WORKFLOW_COLORS.cardBg,
        padding: spacing.md,
        flexDirection: "row",
        alignItems: "center",
        gap: spacing.md,
      }}
    >
      <View
        style={{
          width: 44,
          height: 44,
          borderRadius: moderateScale(12, 0.5),
          backgroundColor: WORKFLOW_COLORS.primarySubtleAlt,
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <AppIcon
          icon={FlowCircleIcon}
          size={24}
          color={WORKFLOW_COLORS.primary}
        />
      </View>

      <View
        style={{
          flex: 1,
          flexDirection: "row",
          flexWrap: "wrap",
          gap: spacing.xs,
        }}
      >
        <AppStatusChip
          status={activation.chipStatus}
          label={activation.label}
        />
        <AppStatusChip
          tone="default"
          label={triggerLabel}
          startContent={
            <AppIcon
              icon={ZapIcon}
              size={11}
              color={WORKFLOW_COLORS.textMuted}
            />
          }
        />
        {workflow.is_public ? (
          <AppStatusChip
            status="success"
            label="Public"
            startContent={
              <AppIcon
                icon={GlobeIcon}
                size={11}
                color={WORKFLOW_COLORS.successText}
              />
            }
          />
        ) : null}
        {workflow.is_system_workflow ? (
          <AppStatusChip tone="accent" label="System" />
        ) : null}
      </View>
    </View>
  );
}
