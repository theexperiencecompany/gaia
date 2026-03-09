import { useRouter } from "expo-router";
import { Pressable, View } from "react-native";
import {
  CheckmarkCircle01Icon,
  FlowCircleIcon,
  HugeiconsIcon,
  PlayIcon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import type { Workflow } from "../types/workflow-types";

interface WorkflowCardProps {
  workflow: Workflow;
}

export function WorkflowCard({ workflow }: WorkflowCardProps) {
  const router = useRouter();
  const { spacing, fontSize, moderateScale } = useResponsive();

  const handlePress = () => {
    router.push(`/(app)/workflows/${workflow.id}`);
  };

  return (
    <Pressable
      onPress={handlePress}
      style={({ pressed }) => ({
        borderRadius: moderateScale(16, 0.5),
        borderWidth: 1,
        borderColor: workflow.activated
          ? "rgba(22,193,255,0.35)"
          : "rgba(255,255,255,0.08)",
        backgroundColor: pressed ? "rgba(255,255,255,0.04)" : "#14171c",
        padding: spacing.md,
        gap: spacing.sm,
      })}
    >
      <View
        style={{
          flexDirection: "row",
          alignItems: "flex-start",
          gap: spacing.sm,
        }}
      >
        <View
          style={{
            width: 36,
            height: 36,
            borderRadius: 10,
            backgroundColor: "rgba(22,193,255,0.12)",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <HugeiconsIcon icon={FlowCircleIcon} size={18} color="#16c1ff" />
        </View>
        <View style={{ flex: 1, gap: 2 }}>
          <Text
            style={{
              fontSize: fontSize.sm,
              fontWeight: "600",
              color: "#e8ebef",
            }}
            numberOfLines={1}
          >
            {workflow.title}
          </Text>
          {workflow.description ? (
            <Text
              style={{ fontSize: fontSize.xs, color: "#8a9099" }}
              numberOfLines={2}
            >
              {workflow.description}
            </Text>
          ) : null}
        </View>
        {workflow.activated && (
          <HugeiconsIcon
            icon={CheckmarkCircle01Icon}
            size={16}
            color="#16c1ff"
          />
        )}
      </View>

      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          gap: spacing.sm,
        }}
      >
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            gap: 4,
            borderRadius: 999,
            paddingHorizontal: spacing.sm,
            paddingVertical: 3,
            backgroundColor: workflow.activated
              ? "rgba(22,193,255,0.15)"
              : "rgba(255,255,255,0.07)",
          }}
        >
          <View
            style={{
              width: 6,
              height: 6,
              borderRadius: 999,
              backgroundColor: workflow.activated ? "#16c1ff" : "#555",
            }}
          />
          <Text
            style={{
              fontSize: fontSize.xs - 1,
              color: workflow.activated ? "#9fe6ff" : "#666",
            }}
          >
            {workflow.activated ? "Active" : "Inactive"}
          </Text>
        </View>

        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            gap: 4,
          }}
        >
          <HugeiconsIcon icon={PlayIcon} size={11} color="#666" />
          <Text style={{ fontSize: fontSize.xs - 1, color: "#666" }}>
            {workflow.total_executions ?? 0} runs
          </Text>
        </View>

        <Text style={{ fontSize: fontSize.xs - 1, color: "#555" }}>
          {workflow.trigger_config?.type ?? "manual"}
        </Text>
      </View>
    </Pressable>
  );
}
