import { Chip } from "heroui-native";
import { Pressable } from "react-native";
import Animated, {
  FadeIn,
  FadeOut,
  LinearTransition,
} from "react-native-reanimated";
import {
  AppIcon,
  Calendar03Icon,
  WorkflowSquare10Icon,
  Wrench01Icon,
} from "@/components/icons";
import { useResponsive } from "@/lib/responsive";

function formatToolName(name: string): string {
  return name
    .toLowerCase()
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ")
    .replace(/\s+tool$/i, "")
    .trim();
}

interface SelectedIndicatorProps {
  label: string;
  variant: "tool" | "workflow" | "calendar";
  onRemove: () => void;
}

export function SelectedIndicator({
  label,
  variant,
  onRemove,
}: SelectedIndicatorProps) {
  const { spacing, iconSize } = useResponsive();

  const icon =
    variant === "workflow"
      ? WorkflowSquare10Icon
      : variant === "calendar"
        ? Calendar03Icon
        : Wrench01Icon;
  const displayLabel = variant === "tool" ? formatToolName(label) : label;

  return (
    <Animated.View
      entering={FadeIn.duration(200)}
      exiting={FadeOut.duration(150)}
      layout={LinearTransition.springify()}
      style={{ alignSelf: "flex-start", marginBottom: spacing.xs }}
    >
      <Chip
        variant="soft"
        color="default"
        size="sm"
        animation="disable-all"
        style={{
          flexDirection: "row",
          alignItems: "center",
          gap: spacing.xs,
          paddingLeft: spacing.sm,
          paddingRight: spacing.xs,
        }}
      >
        <AppIcon icon={icon} size={iconSize.sm} color="#a1a1aa" />
        <Chip.Label>{displayLabel}</Chip.Label>
        <Pressable onPress={onRemove} hitSlop={8} />
      </Chip>
    </Animated.View>
  );
}
