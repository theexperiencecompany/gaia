import { useLocalSearchParams, useRouter } from "expo-router";
import { Pressable, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { AppIcon, ArrowLeft01Icon, Flag02Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { PriorityFilterView } from "@/features/todos/components/priority-filter-view";
import { useResponsive } from "@/lib/responsive";

const PRIORITY_META: Record<string, { label: string; color: string }> = {
  urgent: { label: "Urgent", color: "#ef4444" },
  high: { label: "High", color: "#ef4444" },
  medium: { label: "Medium", color: "#f97316" },
  low: { label: "Low", color: "#eab308" },
  none: { label: "None", color: "#71717a" },
};

export default function PriorityTodosScreen() {
  const { priority } = useLocalSearchParams<{ priority: string }>();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { spacing, fontSize } = useResponsive();

  const decodedPriority = decodeURIComponent(priority ?? "high").toLowerCase();
  const meta = PRIORITY_META[decodedPriority] ?? {
    label: decodedPriority,
    color: "#71717a",
  };

  return (
    <View style={{ flex: 1, backgroundColor: "#131416" }}>
      {/* Header */}
      <View
        style={{
          paddingTop: insets.top + spacing.sm,
          paddingHorizontal: spacing.md,
          paddingBottom: spacing.md,
          borderBottomWidth: 1,
          borderBottomColor: "rgba(255,255,255,0.07)",
          flexDirection: "row",
          alignItems: "center",
          gap: spacing.sm,
        }}
      >
        <Pressable
          onPress={() => router.back()}
          style={{
            width: 36,
            height: 36,
            borderRadius: 999,
            alignItems: "center",
            justifyContent: "center",
            backgroundColor: "rgba(255,255,255,0.05)",
          }}
        >
          <AppIcon icon={ArrowLeft01Icon} size={18} color="#fff" />
        </Pressable>

        <AppIcon icon={Flag02Icon} size={18} color={meta.color} />
        <Text
          style={{
            fontSize: fontSize.lg,
            fontWeight: "600",
            color: "#f4f4f5",
          }}
        >
          {meta.label} Priority
        </Text>
      </View>

      <PriorityFilterView priority={decodedPriority} />
    </View>
  );
}
