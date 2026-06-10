import { View } from "react-native";
import { AppIcon, FlowCircleIcon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { getToolCategoryIcon } from "@/features/chat/utils/tool-icons";
import { useResponsive } from "@/lib/responsive";
import { AppEmptyStateCard } from "@/shared/components/ui/app-empty-state-card";
import { WORKFLOW_COLORS } from "../../constants/colors";
import type { Workflow } from "../../types/workflow-types";

interface WorkflowDetailStepsProps {
  steps: Workflow["steps"];
}

function formatCategoryLabel(category: string): string {
  if (category === "gaia") return "GAIA";
  return category.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function WorkflowDetailSteps({ steps }: WorkflowDetailStepsProps) {
  const { spacing, fontSize } = useResponsive();

  if (steps.length === 0) {
    return (
      <AppEmptyStateCard
        title="No steps generated yet"
        description="Use Regenerate Steps from the menu to draft a plan for this workflow."
        icon={
          <AppIcon
            icon={FlowCircleIcon}
            size={32}
            color={WORKFLOW_COLORS.textZinc700}
          />
        }
        className="rounded-2xl bg-zinc-800/30"
      />
    );
  }

  return (
    <View style={{ position: "relative", paddingBottom: spacing.lg }}>
      <View
        style={{
          position: "absolute",
          left: 13,
          top: 14,
          bottom: 20,
          width: 1,
          backgroundColor: WORKFLOW_COLORS.primaryBorder,
        }}
      />

      <View style={{ gap: spacing.xl }}>
        {steps.map((step, index) => {
          const categoryLabel = formatCategoryLabel(step.category);
          const iconElement = getToolCategoryIcon(step.category, {
            size: 14,
            showBackground: false,
          });

          return (
            <View
              key={step.id}
              style={{
                flexDirection: "row",
                alignItems: "flex-start",
                gap: spacing.md,
              }}
            >
              <View
                style={{
                  width: 28,
                  height: 28,
                  borderRadius: 999,
                  backgroundColor: WORKFLOW_COLORS.primarySubtle,
                  borderWidth: 1,
                  borderColor: WORKFLOW_COLORS.primary,
                  alignItems: "center",
                  justifyContent: "center",
                  zIndex: 1,
                  flexShrink: 0,
                }}
              >
                <Text
                  style={{
                    fontSize: fontSize.xs,
                    fontWeight: "600",
                    color: WORKFLOW_COLORS.primary,
                  }}
                >
                  {index + 1}
                </Text>
              </View>

              <View style={{ flex: 1, gap: spacing.xs, paddingTop: 4 }}>
                <View
                  style={{
                    flexDirection: "row",
                    alignItems: "center",
                    gap: 5,
                    alignSelf: "flex-start",
                    borderRadius: 8,
                    paddingHorizontal: 8,
                    paddingVertical: 4,
                    backgroundColor: WORKFLOW_COLORS.surfaceMutedAlt,
                  }}
                >
                  {iconElement}
                  <Text
                    style={{
                      fontSize: fontSize.xs - 1,
                      color: WORKFLOW_COLORS.textFaint,
                    }}
                  >
                    {categoryLabel}
                  </Text>
                </View>

                <Text
                  style={{
                    fontSize: fontSize.sm,
                    fontWeight: "500",
                    color: WORKFLOW_COLORS.textSecondary,
                    lineHeight: 20,
                  }}
                >
                  {step.title}
                </Text>
                {step.description ? (
                  <Text
                    style={{
                      fontSize: fontSize.xs,
                      color: WORKFLOW_COLORS.textZinc500,
                      lineHeight: 16,
                    }}
                  >
                    {step.description}
                  </Text>
                ) : null}
              </View>
            </View>
          );
        })}
      </View>
    </View>
  );
}
