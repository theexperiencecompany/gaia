import { Pressable, View } from "react-native";
import { FlowCircleIcon, HugeiconsIcon, UserIcon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import type { CommunityWorkflow } from "../types/workflow-types";

interface CommunityWorkflowCardProps {
  workflow: CommunityWorkflow;
  onPress?: (workflow: CommunityWorkflow) => void;
}

export function CommunityWorkflowCard({
  workflow,
  onPress,
}: CommunityWorkflowCardProps) {
  const { spacing, fontSize, moderateScale } = useResponsive();

  return (
    <Pressable
      onPress={() => onPress?.(workflow)}
      style={({ pressed }) => ({
        borderRadius: moderateScale(14, 0.5),
        borderWidth: 1,
        borderColor: "rgba(255,255,255,0.07)",
        backgroundColor: pressed ? "rgba(255,255,255,0.04)" : "#111318",
        padding: spacing.md,
        gap: spacing.xs,
      })}
    >
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          gap: spacing.sm,
        }}
      >
        <HugeiconsIcon icon={FlowCircleIcon} size={14} color="#555" />
        <Text
          style={{
            fontSize: fontSize.sm,
            fontWeight: "600",
            color: "#d0d5dd",
            flex: 1,
          }}
          numberOfLines={1}
        >
          {workflow.title}
        </Text>
      </View>

      {workflow.description ? (
        <Text
          style={{ fontSize: fontSize.xs, color: "#6b7280" }}
          numberOfLines={2}
        >
          {workflow.description}
        </Text>
      ) : null}

      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          gap: spacing.sm,
          marginTop: 2,
        }}
      >
        <HugeiconsIcon icon={UserIcon} size={11} color="#4b5563" />
        <Text style={{ fontSize: fontSize.xs - 1, color: "#4b5563" }}>
          {workflow.creator.name}
        </Text>
        {(workflow.total_executions ?? 0) > 0 && (
          <Text style={{ fontSize: fontSize.xs - 1, color: "#4b5563" }}>
            · {workflow.total_executions} runs
          </Text>
        )}
      </View>
    </Pressable>
  );
}
