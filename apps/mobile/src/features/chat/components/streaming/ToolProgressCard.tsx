import { useEffect } from "react";
import { View } from "react-native";
import Animated, {
  useAnimatedStyle,
  useSharedValue,
  withRepeat,
  withSequence,
  withTiming,
} from "react-native-reanimated";
import {
  AppIcon,
  Brain02Icon,
  Calendar03Icon,
  CheckmarkCircle01Icon,
  CpuIcon,
  Mail01Icon,
  Search01Icon,
  Settings01Icon,
  TaskDailyIcon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";

type IconComponent = React.ComponentType<{
  size?: number;
  color?: string;
  strokeWidth?: number;
}>;

function getToolIcon(toolName: string | null): IconComponent {
  if (!toolName) return Brain02Icon;
  const lower = toolName.toLowerCase();
  if (lower.includes("search") || lower.includes("web")) return Search01Icon;
  if (lower.includes("email") || lower.includes("mail")) return Mail01Icon;
  if (
    lower.includes("calendar") ||
    lower.includes("event") ||
    lower.includes("schedule")
  )
    return Calendar03Icon;
  if (lower.includes("todo") || lower.includes("task")) return TaskDailyIcon;
  if (
    lower.includes("memory") ||
    lower.includes("remember") ||
    lower.includes("recall")
  )
    return CpuIcon;
  if (lower.includes("setting") || lower.includes("config"))
    return Settings01Icon;
  if (
    lower.includes("done") ||
    lower.includes("complete") ||
    lower.includes("finish")
  )
    return CheckmarkCircle01Icon;
  return Brain02Icon;
}

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
}

export function ToolProgressCard({
  toolName,
  progressMessage,
}: ToolProgressCardProps) {
  const { spacing, fontSize, iconSize } = useResponsive();

  const pulseOpacity = useSharedValue(0.5);
  useEffect(() => {
    pulseOpacity.value = withRepeat(
      withSequence(
        withTiming(1, { duration: 600 }),
        withTiming(0.5, { duration: 600 }),
      ),
      -1,
      false,
    );
  }, [pulseOpacity]);

  const pulseStyle = useAnimatedStyle(() => ({
    opacity: pulseOpacity.value,
  }));

  const ToolIcon = getToolIcon(toolName);
  const message = progressMessage || formatToolName(toolName);

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
        <AppIcon
          icon={ToolIcon}
          size={iconSize.sm}
          color="#00bbff"
          strokeWidth={1.5}
        />
      </Animated.View>
      <Text
        style={{
          fontSize: fontSize.sm,
          color: "#71717a",
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
