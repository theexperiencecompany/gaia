import { Card, Chip } from "heroui-native";
import { useEffect, useRef, useState } from "react";
import { View } from "react-native";
import Animated, {
  useAnimatedStyle,
  useSharedValue,
  withRepeat,
  withSequence,
  withTiming,
} from "react-native-reanimated";
import {
  Brain02Icon,
  Calendar03Icon,
  CheckmarkCircle01Icon,
  CpuIcon,
  Mail01Icon,
  Search01Icon,
  Settings01Icon,
  TaskDailyIcon,
} from "@/components/icons";
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

function useElapsedTime(): number {
  const [elapsed, setElapsed] = useState(0);
  const startRef = useRef(Date.now());

  useEffect(() => {
    startRef.current = Date.now();
    setElapsed(0);
    const interval = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startRef.current) / 1000));
    }, 1000);
    return () => clearInterval(interval);
  }, []);

  return elapsed;
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
  const elapsed = useElapsedTime();

  const pulseOpacity = useSharedValue(1);

  useEffect(() => {
    pulseOpacity.value = withRepeat(
      withSequence(
        withTiming(0.5, { duration: 800 }),
        withTiming(1, { duration: 800 }),
      ),
      -1,
      false,
    );
  }, [pulseOpacity]);

  const pulseStyle = useAnimatedStyle(() => ({
    opacity: pulseOpacity.value,
  }));

  const ToolIcon = getToolIcon(toolName);
  const displayName = formatToolName(toolName);
  const message = progressMessage || displayName;

  return (
    <Card
      variant="secondary"
      animation="disable-all"
      style={{
        flexDirection: "row",
        alignItems: "center",
        paddingVertical: spacing.sm,
        paddingHorizontal: spacing.md,
        gap: spacing.sm,
        backgroundColor: "rgba(0,187,255,0.06)",
        borderColor: "rgba(0,187,255,0.15)",
      }}
    >
      <Animated.View style={pulseStyle}>
        <ToolIcon size={iconSize.md} color="#00bbff" strokeWidth={1.5} />
      </Animated.View>

      <View style={{ flex: 1 }}>
        <Card.Title
          style={{
            fontSize: fontSize.sm,
            color: "#ffffff",
            fontWeight: "500",
          }}
          numberOfLines={2}
        >
          {message}
        </Card.Title>
      </View>

      {elapsed > 0 && (
        <Chip size="sm" variant="soft" color="default" animation="disable-all">
          <Chip.Label>{elapsed}s</Chip.Label>
        </Chip>
      )}
    </Card>
  );
}
