import { useRouter } from "expo-router";
import { useState } from "react";
import { Alert, Image, Pressable, ScrollView, View } from "react-native";
import {
  SafeAreaView,
  useSafeAreaInsets,
} from "react-native-safe-area-context";
import {
  Analytics01Icon,
  AppIcon,
  ArrowRight01Icon,
  BrainIcon,
  ConnectIcon,
  CreditCardIcon,
  Logout01Icon,
  Notification01Icon,
  Settings01Icon,
  UserCircle02Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useAuth } from "@/features/auth/hooks/use-auth";
import { AccountSection } from "@/features/settings/components/sections/account-section";
import { LinkedAccountsSection } from "@/features/settings/components/sections/linked-accounts-section";
import { MemorySection } from "@/features/settings/components/sections/memory-section";
import { NotificationSection } from "@/features/settings/components/sections/notification-section";
import { PreferencesSection } from "@/features/settings/components/sections/preferences-section";
import { ProfileSection } from "@/features/settings/components/sections/profile-section";
import { SubscriptionSection } from "@/features/settings/components/sections/subscription-section";
import { UsageSection } from "@/features/settings/components/sections/usage-section";
import { useResponsive } from "@/lib/responsive";
import { BackButton } from "@/shared/components/ui/back-button";
import { SettingsGroup, SettingsRow } from "./settings-row";

export type SettingsSection =
  | "account"
  | "profile"
  | "preferences"
  | "notifications"
  | "linked-accounts"
  | "memory"
  | "usage"
  | "subscription";

const SECTION_LABELS: Record<SettingsSection, string> = {
  account: "Account",
  profile: "Profile",
  preferences: "Preferences",
  notifications: "Notifications",
  "linked-accounts": "Linked Accounts",
  memory: "Memory",
  usage: "Usage",
  subscription: "Subscription",
};

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

interface SettingsHeaderProps {
  title: string;
  onBack: () => void;
}

function SettingsHeader({ title, onBack }: SettingsHeaderProps) {
  const insets = useSafeAreaInsets();
  const { spacing, fontSize } = useResponsive();

  return (
    <View
      style={{
        paddingTop: insets.top + spacing.xs,
        paddingHorizontal: spacing.md,
        paddingBottom: spacing.sm + 2,
        flexDirection: "row",
        alignItems: "center",
        borderBottomWidth: 1,
        borderBottomColor: "rgba(255,255,255,0.06)",
        gap: spacing.sm,
      }}
    >
      <BackButton onPress={onBack} hideWhenCannotGoBack={false} />
      <Text
        style={{
          fontSize: fontSize.lg,
          fontWeight: "700",
          color: "#ffffff",
          letterSpacing: -0.3,
        }}
      >
        {title}
      </Text>
    </View>
  );
}

interface SettingsMenuProps {
  onSelect: (section: SettingsSection) => void;
}

function SettingsMenu({ onSelect }: SettingsMenuProps) {
  const { user, signOut } = useAuth();
  const router = useRouter();
  const { spacing, fontSize } = useResponsive();

  const handleSignOut = () => {
    Alert.alert("Sign Out", "Are you sure you want to sign out?", [
      { text: "Cancel", style: "cancel" },
      {
        text: "Sign Out",
        style: "destructive",
        onPress: async () => {
          await signOut();
          router.replace("/login");
        },
      },
    ]);
  };

  const getInitials = (name?: string) => {
    if (!name) return "U";
    const parts = name.trim().split(" ");
    if (parts.length >= 2)
      return `${parts[0][0]}${parts[parts.length - 1][0]}`.toUpperCase();
    return name[0].toUpperCase();
  };

  return (
    <ScrollView
      showsVerticalScrollIndicator={false}
      contentContainerStyle={{ padding: spacing.md, gap: spacing.lg }}
    >
      {/* Profile hero */}
      <Pressable
        onPress={() => onSelect("account")}
        style={({ pressed }) => ({
          flexDirection: "row",
          alignItems: "center",
          gap: spacing.md,
          backgroundColor: pressed
            ? "rgba(255,255,255,0.05)"
            : "rgba(255,255,255,0.03)",
          borderRadius: 16,
          padding: spacing.md,
        })}
      >
        <View
          style={{
            width: 52,
            height: 52,
            borderRadius: 26,
            backgroundColor: "#18181b",
            alignItems: "center",
            justifyContent: "center",
            overflow: "hidden",
          }}
        >
          {user?.picture ? (
            <Image
              source={{ uri: user.picture }}
              style={{ width: 52, height: 52 }}
            />
          ) : (
            <Text
              style={{
                color: "#00bbff",
                fontWeight: "700",
                fontSize: fontSize.lg,
              }}
            >
              {getInitials(user?.name)}
            </Text>
          )}
        </View>
        <View style={{ flex: 1 }}>
          <Text
            style={{
              fontSize: fontSize.base,
              fontWeight: "600",
              color: "#ffffff",
            }}
            numberOfLines={1}
          >
            {user?.name || "User"}
          </Text>
          <Text
            style={{
              fontSize: fontSize.xs,
              color: "#71717a",
              marginTop: 1,
            }}
            numberOfLines={1}
          >
            {user?.email || ""}
          </Text>
          <View
            style={{
              marginTop: 4,
              alignSelf: "flex-start",
              backgroundColor: "rgba(0,187,255,0.12)",
              borderRadius: 4,
              paddingHorizontal: 6,
              paddingVertical: 1,
            }}
          >
            <Text
              style={{
                fontSize: 10,
                color: "#00bbff",
                fontWeight: "400",
              }}
            >
              GAIA Free
            </Text>
          </View>
        </View>
        <AppIcon icon={ArrowRight01Icon} size={16} color="#3a3a3c" />
      </Pressable>

      {/* General */}
      <SettingsGroup label="General">
        <SettingsRow
          icon={UserCircle02Icon}
          iconBg="rgba(0,187,255,0.12)"
          iconColor="#00bbff"
          title="Profile"
          subtitle="Edit your display name and avatar"
          showChevron
          onPress={() => onSelect("profile")}
        />
        <SettingsRow
          icon={Settings01Icon}
          iconBg="rgba(255,255,255,0.07)"
          iconColor="#71717a"
          title="Preferences"
          subtitle="Theme, language, and display options"
          showChevron
          onPress={() => onSelect("preferences")}
        />
        <SettingsRow
          icon={Notification01Icon}
          iconBg="rgba(255,255,255,0.07)"
          iconColor="#71717a"
          title="Notifications"
          subtitle="Alerts, sounds, and delivery settings"
          showChevron
          isLast
          onPress={() => onSelect("notifications")}
        />
      </SettingsGroup>

      {/* Intelligence */}
      <SettingsGroup label="Intelligence">
        <SettingsRow
          icon={BrainIcon}
          iconBg="rgba(255,255,255,0.07)"
          iconColor="#71717a"
          title="Memory"
          subtitle="What GAIA remembers about you"
          showChevron
          isLast
          onPress={() => onSelect("memory")}
        />
      </SettingsGroup>

      {/* Connections */}
      <SettingsGroup label="Connections">
        <SettingsRow
          icon={ConnectIcon}
          iconBg="rgba(34,197,94,0.12)"
          iconColor="#22c55e"
          title="Linked Accounts"
          subtitle="Telegram, and more"
          showChevron
          isLast
          onPress={() => onSelect("linked-accounts")}
        />
      </SettingsGroup>

      {/* Billing */}
      <SettingsGroup label="Billing">
        <SettingsRow
          icon={Analytics01Icon}
          iconBg="rgba(255,255,255,0.07)"
          iconColor="#71717a"
          title="Usage"
          subtitle="Messages and API usage this month"
          showChevron
          onPress={() => onSelect("usage")}
        />
        <SettingsRow
          icon={CreditCardIcon}
          iconBg="rgba(255,255,255,0.07)"
          iconColor="#71717a"
          title="Subscription"
          subtitle="Manage your plan and billing"
          showChevron
          isLast
          onPress={() => onSelect("subscription")}
        />
      </SettingsGroup>

      {/* Danger zone */}
      <SettingsGroup>
        <SettingsRow
          icon={Logout01Icon}
          title="Sign Out"
          isDestructive
          isLast
          onPress={handleSignOut}
        />
      </SettingsGroup>

      <View style={{ height: spacing.lg }} />
    </ScrollView>
  );
}

export function SettingsShell() {
  const router = useRouter();
  const [activeSection, setActiveSection] = useState<SettingsSection | null>(
    null,
  );

  if (activeSection) {
    const SectionComponent = SECTION_COMPONENTS[activeSection];
    return (
      <SafeAreaView
        style={{ flex: 1, backgroundColor: "#111111" }}
        edges={["bottom"]}
      >
        <SettingsHeader
          title={SECTION_LABELS[activeSection]}
          onBack={() => setActiveSection(null)}
        />
        <SectionComponent />
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView
      style={{ flex: 1, backgroundColor: "#111111" }}
      edges={["bottom"]}
    >
      <SettingsHeader title="Settings" onBack={() => router.back()} />
      <SettingsMenu onSelect={setActiveSection} />
    </SafeAreaView>
  );
}
