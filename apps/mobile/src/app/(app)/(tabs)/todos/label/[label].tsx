import { useLocalSearchParams } from "expo-router";
import { View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Text } from "@/components/ui/text";
import { LabelChip } from "@/features/todos/components/label-chip";
import { LabelFilterView } from "@/features/todos/components/label-filter-view";
import { useResponsive } from "@/lib/responsive";
import { BackButton } from "@/shared/components/ui/back-button";

export default function LabelFilterPage() {
  const { label } = useLocalSearchParams<{ label: string }>();
  const insets = useSafeAreaInsets();
  const { spacing, fontSize } = useResponsive();

  const decodedLabel = decodeURIComponent(label ?? "");

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
        <BackButton />

        <Text
          style={{
            fontSize: fontSize.lg,
            fontWeight: "600",
            color: "#f4f4f5",
            marginRight: spacing.sm,
          }}
        >
          Label:
        </Text>
        <LabelChip label={decodedLabel} size="md" />
      </View>

      <LabelFilterView label={decodedLabel} />
    </View>
  );
}
