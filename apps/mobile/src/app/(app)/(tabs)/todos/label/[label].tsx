import { useLocalSearchParams, useRouter } from "expo-router";
import { Pressable, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { AppIcon, ArrowLeft01Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { LabelChip, LabelFilterView } from "@/features/todos";
import { useResponsive } from "@/lib/responsive";

export default function LabelFilterPage() {
  const { label } = useLocalSearchParams<{ label: string }>();
  const router = useRouter();
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
