import * as Haptics from "expo-haptics";
import { Pressable, View } from "react-native";
import {
  AppIcon,
  PlayIcon,
  Tag01Icon,
  UserCircle02Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { WORKFLOW_COLORS } from "../constants/colors";
import type { CommunityWorkflow } from "../types/workflow-types";
import { formatRunCount } from "../utils/format-utils";
import { WorkflowStepIcons } from "./workflow-step-icons";

interface CommunityWorkflowCardProps {
  workflow: CommunityWorkflow;
  onPress?: (workflow: CommunityWorkflow) => void;
}

export function CommunityWorkflowCard({
  workflow,
  onPress,
}: CommunityWorkflowCardProps) {
  const { spacing, fontSize, moderateScale } = useResponsive();
  const runCountText = formatRunCount(workflow.total_executions ?? 0);

  const handlePress = () => {
    void Haptics.selectionAsync();
    onPress?.(workflow);
  };

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
      <WorkflowStepIcons steps={workflow.steps} />

      <View>
        <Text
          style={{
            fontSize: fontSize.base,
            fontWeight: "500",
            color: WORKFLOW_COLORS.textPrimary,
          }}
          numberOfLines={2}
        >
          {workflow.title}
        </Text>
        {workflow.description ? (
          <Text
            style={{
              fontSize: fontSize.xs,
              color: WORKFLOW_COLORS.textZinc500,
              marginTop: 4,
              lineHeight: 16,
            }}
            numberOfLines={2}
          >
            {workflow.description}
          </Text>
        ) : null}
      </View>

      {workflow.categories && workflow.categories.length > 0 ? (
        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
          {workflow.categories.slice(0, 3).map((cat) => (
            <View
              key={cat}
              style={{
                flexDirection: "row",
                alignItems: "center",
                gap: 3,
                paddingHorizontal: 7,
                paddingVertical: 2,
                borderRadius: 6,
                backgroundColor: WORKFLOW_COLORS.surfaceMutedAlt,
              }}
            >
              <AppIcon
                icon={Tag01Icon}
                size={10}
                color={WORKFLOW_COLORS.textZinc500}
              />
              <Text
                style={{
                  fontSize: fontSize.xs - 1,
                  color: WORKFLOW_COLORS.textZinc500,
                }}
              >
                {cat}
              </Text>
            </View>
          ))}
        </View>
      ) : null}

      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          justifyContent: "space-between",
          marginTop: 2,
          flexWrap: "wrap",
          gap: 6,
        }}
      >
        <View style={{ flexDirection: "row", alignItems: "center", gap: 10 }}>
          {runCountText !== "Never run" ? (
            <View
              style={{ flexDirection: "row", alignItems: "center", gap: 4 }}
            >
              <AppIcon
                icon={PlayIcon}
                size={13}
                color={WORKFLOW_COLORS.textZinc500}
              />
              <Text
                style={{
                  fontSize: fontSize.xs,
                  color: WORKFLOW_COLORS.textZinc500,
                }}
              >
                {runCountText}
              </Text>
            </View>
          ) : null}
        </View>

        {workflow.creator ? (
          <View style={{ flexDirection: "row", alignItems: "center", gap: 5 }}>
            <AppIcon
              icon={UserCircle02Icon}
              size={18}
              color={WORKFLOW_COLORS.textZinc500}
            />
            <Text
              style={{
                fontSize: fontSize.xs - 1,
                color: WORKFLOW_COLORS.textZinc500,
              }}
            >
              {workflow.creator.name}
            </Text>
          </View>
        ) : null}
      </View>
    </Pressable>
  );
}
