import { useEffect } from "react";
import { View } from "react-native";
import Animated, {
  useAnimatedStyle,
  useSharedValue,
  withRepeat,
  withSequence,
  withTiming,
} from "react-native-reanimated";
import { AppIcon, Brain02Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { getToolCategoryIcon } from "@/features/chat/utils/tool-icons";
import { useResponsive } from "@/lib/responsive";

function formatToolName(toolName: string | null): string {
  if (!toolName) return "Processing";
  return toolName
    .replace(/_/g, " ")
    .replace(/([A-Z])/g, " $1")
    .trim()
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

interface ToolProgressCardProps {
  toolName: string | null;
  progressMessage: string | null;
  toolCategory?: string | null;
  toolIconUrl?: string | null;
}

export function ToolProgressCard({
  toolName,
  progressMessage,
  toolCategory,
  toolIconUrl,
}: ToolProgressCardProps) {
  const { spacing, fontSize, moderateScale } = useResponsive();
  const iconSize = moderateScale(16, 0.5);

  const pulseOpacity = useSharedValue(0.6);
  useEffect(() => {
    pulseOpacity.value = withRepeat(
      withSequence(
        withTiming(1, { duration: 600 }),
        withTiming(0.6, { duration: 600 }),
      ),
      -1,
      false,
    );
  }, [pulseOpacity]);

  const pulseStyle = useAnimatedStyle(() => ({
    opacity: pulseOpacity.value,
  }));

  const message = progressMessage || formatToolName(toolName);

  const categoryIcon = toolCategory
    ? getToolCategoryIcon(
        toolCategory,
        { size: iconSize, showBackground: false },
        toolIconUrl ?? undefined,
      )
    : null;

  return (
    <View
      style={{
        flexDirection: "row",
        alignItems: "center",
        gap: spacing.sm,
        paddingVertical: spacing.xs,
      }}
    >
      <Animated.View style={pulseStyle}>
        {categoryIcon ?? (
          <AppIcon
            icon={Brain02Icon}
            size={iconSize}
            color="#a1a1aa"
            strokeWidth={1.5}
          />
        )}
      </Animated.View>
      <Text
        style={{
          fontSize: fontSize.sm,
          color: "#a1a1aa",
          fontWeight: "500",
          flex: 1,
        }}
        numberOfLines={2}
      >
        {message}
      </Text>
    </View>
  );
}
