import { Pressable } from "react-native";
import Animated, {
  FadeIn,
  FadeOut,
  LinearTransition,
} from "react-native-reanimated";
import {
  Calendar03Icon,
  Cancel01Icon,
  AppIcon,
  WorkflowSquare10Icon,
  Wrench01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
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
  const { spacing, fontSize, iconSize } = useResponsive();

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
      style={{
        flexDirection: "row",
        alignItems: "center",
        alignSelf: "flex-start",
        backgroundColor: "#3f3f46",
        borderRadius: 12,
        paddingLeft: spacing.sm,
        paddingRight: spacing.xs,
        paddingVertical: spacing.xs,
        marginBottom: spacing.xs,
        gap: spacing.xs,
      }}
    >
      <AppIcon icon={icon} size={iconSize.sm} color="#a1a1aa" />
      <Text
        style={{
          fontSize: fontSize.sm,
          color: "#e4e4e7",
          fontWeight: "300",
        }}
        numberOfLines={1}
      >
        {displayLabel}
      </Text>
      <Pressable
        onPress={onRemove}
        hitSlop={8}
        style={{
          width: 22,
          height: 22,
          borderRadius: 6,
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <AppIcon
          icon={Cancel01Icon}
          size={iconSize.sm - 2}
          color="#a1a1aa"
        />
      </Pressable>
    </Animated.View>
  );
}
