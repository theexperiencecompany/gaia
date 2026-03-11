import { useRouter } from "expo-router";
import { useState } from "react";
import { Pressable, ScrollView, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { AppIcon, ArrowLeft01Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { AccountSection } from "@/features/settings/components/sections/account-section";
import { LinkedAccountsSection } from "@/features/settings/components/sections/linked-accounts-section";
import { MemorySection } from "@/features/settings/components/sections/memory-section";
import { NotificationSection } from "@/features/settings/components/sections/notification-section";
import { PreferencesSection } from "@/features/settings/components/sections/preferences-section";
import { ProfileSection } from "@/features/settings/components/sections/profile-section";
import { SubscriptionSection } from "@/features/settings/components/sections/subscription-section";
import { UsageSection } from "@/features/settings/components/sections/usage-section";
import { useResponsive } from "@/lib/responsive";

export type SettingsSection =
  | "account"
  | "profile"
  | "preferences"
  | "notifications"
  | "linked-accounts"
  | "memory"
  | "usage"
  | "subscription";

const TABS: { key: SettingsSection; label: string }[] = [
  { key: "account", label: "Account" },
  { key: "profile", label: "Profile" },
  { key: "preferences", label: "Preferences" },
  { key: "notifications", label: "Notifications" },
  { key: "linked-accounts", label: "Linked Accounts" },
  { key: "memory", label: "Memory" },
  { key: "usage", label: "Usage" },
  { key: "subscription", label: "Subscription" },
];

const SECTION_COMPONENTS: Record<SettingsSection, React.ComponentType> = {
  account: AccountSection,
  profile: ProfileSection,
  preferences: PreferencesSection,
  notifications: NotificationSection,
  "linked-accounts": LinkedAccountsSection,
  memory: MemorySection,
  usage: UsageSection,
  subscription: SubscriptionSection,
};

export function SettingsShell() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { spacing, fontSize } = useResponsive();
  const [activeSection, setActiveSection] =
    useState<SettingsSection>("account");
  const ActiveSectionComponent = SECTION_COMPONENTS[activeSection];

  return (
    <View style={{ flex: 1, backgroundColor: "#0b0c0f" }}>
      <View
        style={{
          paddingTop: insets.top + spacing.sm,
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
            <AppIcon icon={ArrowLeft01Icon} size={18} color="#fff" />
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
                onPress={() => setActiveSection(key)}
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

      <View style={{ flex: 1 }}>
        <ActiveSectionComponent />
      </View>
    </View>
  );
}
