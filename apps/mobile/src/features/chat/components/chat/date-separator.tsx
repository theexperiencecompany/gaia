import Animated, { FadeIn } from "react-native-reanimated";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { Divider } from "@/shared/components/ui/divider";

interface DateSeparatorProps {
  date: string;
}

function formatDateLabel(dateStr: string): string {
  const date = new Date(dateStr);
  const now = new Date();

  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);

  const target = new Date(date.getFullYear(), date.getMonth(), date.getDate());

  if (target.getTime() === today.getTime()) return "Today";
  if (target.getTime() === yesterday.getTime()) return "Yesterday";

  return date.toLocaleDateString("en-US", { month: "long", day: "numeric" });
}

export function DateSeparator({ date }: DateSeparatorProps) {
  const { spacing, fontSize } = useResponsive();
  const label = formatDateLabel(date);

  return (
    <Animated.View
      entering={FadeIn.duration(200)}
      style={{
        flexDirection: "row",
        alignItems: "center",
        paddingVertical: spacing.sm,
        paddingHorizontal: spacing.md,
      }}
    >
      <Divider style={{ flex: 1 }} />
      <Text
        style={{
          fontSize: fontSize.xs,
          fontWeight: "500",
          color: "rgba(255,255,255,0.3)",
          marginHorizontal: spacing.sm,
          textTransform: "uppercase",
          letterSpacing: 0.8,
        }}
      >
        {label}
      </Text>
      <Divider style={{ flex: 1 }} />
    </Animated.View>
  );
}
