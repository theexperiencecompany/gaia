import { Divider } from "heroui-native";
import { View } from "react-native";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";

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
    <View
      style={{
        flexDirection: "row",
        alignItems: "center",
        paddingVertical: spacing.md,
        paddingHorizontal: spacing.lg,
      }}
    >
      <Divider style={{ flex: 1 }} />
      <Text
        style={{
          fontSize: fontSize.xs,
          fontWeight: "500",
          color: "rgba(255,255,255,0.4)",
          marginHorizontal: spacing.sm,
        }}
      >
        {label}
      </Text>
      <Divider style={{ flex: 1 }} />
    </View>
  );
}
