import { useRouter } from "expo-router";
import { Pressable, ScrollView, View } from "react-native";
import { ArrowLeft01Icon, HugeiconsIcon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";

export type SettingsSection =
  | "account"
  | "preferences"
  | "notifications"
  | "usage";

const TABS: { key: SettingsSection; label: string }[] = [
  { key: "account", label: "Account" },
  { key: "preferences", label: "Preferences" },
  { key: "notifications", label: "Notifications" },
  { key: "usage", label: "Usage" },
];

interface SettingsShellProps {
  activeSection: SettingsSection;
  onSectionChange: (section: SettingsSection) => void;
  children: React.ReactNode;
}

export function SettingsShell({
  activeSection,
  onSectionChange,
  children,
}: SettingsShellProps) {
  const router = useRouter();
  const { spacing, fontSize } = useResponsive();

  return (
    <View style={{ flex: 1, backgroundColor: "#0b0c0f" }}>
      {/* Header */}
      <View
        style={{
          paddingTop: spacing.xl * 2,
          paddingHorizontal: spacing.md,
          paddingBottom: spacing.md,
          borderBottomWidth: 1,
          borderBottomColor: "rgba(255,255,255,0.08)",
          gap: spacing.md,
        }}
      >
        <View style={{ flexDirection: "row", alignItems: "center" }}>
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
            <HugeiconsIcon icon={ArrowLeft01Icon} size={18} color="#fff" />
          </Pressable>
          <Text
            style={{
              marginLeft: spacing.md,
              fontSize: fontSize.base,
              fontWeight: "600",
            }}
          >
            Settings
          </Text>
        </View>

        {/* Section tabs */}
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={{ gap: spacing.sm }}
        >
          {TABS.map(({ key, label }) => {
            const isActive = activeSection === key;
            return (
              <Pressable
                key={key}
                onPress={() => onSectionChange(key)}
                style={{
                  borderRadius: 999,
                  paddingHorizontal: spacing.md,
                  paddingVertical: spacing.xs,
                  backgroundColor: isActive
                    ? "rgba(22,193,255,0.2)"
                    : "rgba(255,255,255,0.07)",
                }}
              >
                <Text
                  style={{
                    fontSize: fontSize.xs,
                    color: isActive ? "#9fe6ff" : "#c5cad2",
                    fontWeight: isActive ? "600" : "400",
                  }}
                >
                  {label}
                </Text>
              </Pressable>
            );
          })}
        </ScrollView>
      </View>

      {/* Content */}
      <View style={{ flex: 1 }}>{children}</View>
    </View>
  );
}
