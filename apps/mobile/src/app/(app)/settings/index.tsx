import Constants from "expo-constants";
import { useRouter } from "expo-router";
import { Avatar } from "heroui-native";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Image,
  Linking,
  Pressable,
  ScrollView,
  Switch,
  TextInput,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import {
  AppIcon,
  ArrowLeft01Icon,
  ArrowRight01Icon,
  BrainIcon,
  ChartLineData02Icon,
  CreditCardIcon,
  CustomerSupportIcon,
  DiscordIcon,
  DocumentAttachmentIcon,
  FlashIcon,
  GlobeIcon,
  InformationCircleIcon,
  Logout01Icon,
  Mail01Icon,
  Notification01Icon,
  Settings02Icon,
  ShieldUserIcon,
  TelegramIcon,
  ToolsIcon,
  TranslationIcon,
  UserCircle02Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useAuth } from "@/features/auth";
import type {
  ChannelPreferences,
  OnboardingPreferences,
  UsageSummary,
} from "@/features/settings/api/settings-api";
import { settingsApi } from "@/features/settings/api/settings-api";
import type { ThemeMode } from "@/lib/theme-store";
import { useThemeStore } from "@/lib/theme-store";
import { useResponsive } from "@/lib/responsive";

// ─── Color tokens ─────────────────────────────────────────────────────────────
const C = {
  bg: "#131416",
  sectionBg: "#171920",
  divider: "rgba(255,255,255,0.06)",
  text: "#ffffff",
  textMuted: "#8e8e93",
  textSubtle: "#5a5a5e",
  primary: "#00bbff",
  primaryBg: "rgba(0,187,255,0.15)",
  primaryBorder: "rgba(0,187,255,0.35)",
  danger: "#ef4444",
  dangerBg: "rgba(239,68,68,0.1)",
  warning: "#f59e0b",
  success: "#22c55e",
  iconBg: "rgba(255,255,255,0.07)",
};

// ─── Layout primitives ────────────────────────────────────────────────────────

function SettingsPage({ children }: { children: React.ReactNode }) {
  const { spacing } = useResponsive();
  return (
    <View style={{ gap: spacing.lg, paddingHorizontal: spacing.md }}>
      {children}
    </View>
  );
}

function SettingsSection({
  title,
  description,
  children,
}: {
  title?: string;
  description?: string;
  children: React.ReactNode;
}) {
  const { fontSize, spacing } = useResponsive();
  return (
    <View>
      {title ? (
        <Text
          style={{
            fontSize: fontSize.xs,
            fontWeight: "600",
            textTransform: "uppercase",
            letterSpacing: 0.8,
            color: C.textMuted,
            marginBottom: spacing.xs,
            paddingHorizontal: 4,
          }}
        >
          {title}
        </Text>
      ) : null}
      {description ? (
        <Text
          style={{
            fontSize: fontSize.sm,
            color: C.textMuted,
            marginBottom: spacing.sm,
            paddingHorizontal: 4,
          }}
        >
          {description}
        </Text>
      ) : null}
      <View
        style={{
          backgroundColor: C.sectionBg,
          borderRadius: 16,
          overflow: "hidden",
        }}
      >
        {children}
      </View>
    </View>
  );
}

function RowDivider() {
  return (
    <View
      style={{
        height: 1,
        backgroundColor: C.divider,
        marginHorizontal: 16,
      }}
    />
  );
}

interface SettingsRowProps {
  label: string;
  description?: string;
  icon?: React.ReactNode;
  iconBgColor?: string;
  children?: React.ReactNode;
  variant?: "default" | "danger";
  onPress?: () => void;
  showChevron?: boolean;
  stacked?: boolean;
}

function SettingsRow({
  label,
  description,
  icon,
  iconBgColor,
  children,
  variant = "default",
  onPress,
  showChevron = false,
  stacked = false,
}: SettingsRowProps) {
  const { spacing, fontSize } = useResponsive();
  const labelColor = variant === "danger" ? C.danger : C.text;

  const iconContainer = icon ? (
    <View
      style={{
        width: 34,
        height: 34,
        borderRadius: 9,
        backgroundColor: iconBgColor ?? C.iconBg,
        alignItems: "center",
        justifyContent: "center",
        flexShrink: 0,
      }}
    >
      {icon}
    </View>
  ) : null;

  const content = stacked ? (
    <View style={{ padding: spacing.md }}>
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          gap: spacing.sm + 2,
          marginBottom: children ? spacing.sm : 0,
        }}
      >
        {iconContainer}
        <View>
          <Text
            style={{
              fontSize: fontSize.sm + 1,
              color: labelColor,
              fontWeight: "400",
            }}
          >
            {label}
          </Text>
          {description ? (
            <Text
              style={{
                fontSize: fontSize.xs,
                color: C.textMuted,
                marginTop: 2,
              }}
            >
              {description}
            </Text>
          ) : null}
        </View>
      </View>
      {children ? <View>{children}</View> : null}
    </View>
  ) : (
    <View
      style={{
        flexDirection: "row",
        alignItems: "center",
        paddingHorizontal: spacing.md,
        paddingVertical: 13,
        minHeight: 52,
      }}
    >
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          gap: spacing.sm + 2,
          flex: 1,
          minWidth: 0,
        }}
      >
        {iconContainer}
        <View style={{ flex: 1, minWidth: 0 }}>
          <Text
            style={{
              fontSize: fontSize.sm + 1,
              color: labelColor,
              fontWeight: "400",
            }}
          >
            {label}
          </Text>
          {description ? (
            <Text
              style={{
                fontSize: fontSize.xs,
                color: C.textMuted,
                marginTop: 2,
              }}
            >
              {description}
            </Text>
          ) : null}
        </View>
      </View>
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          gap: spacing.sm,
          flexShrink: 0,
          marginLeft: spacing.sm,
        }}
      >
        {children}
        {showChevron ? (
          <AppIcon icon={ArrowRight01Icon} size={16} color={C.textMuted} />
        ) : null}
      </View>
    </View>
  );

  if (onPress) {
    return <Pressable onPress={onPress}>{content}</Pressable>;
  }

  return content;
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function getInitials(name?: string): string {
  if (!name) return "U";
  const parts = name.trim().split(" ");
  if (parts.length >= 2) {
    return `${parts[0][0]}${parts[parts.length - 1][0]}`.toUpperCase();
  }
  return name[0].toUpperCase();
}

function getDeviceTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone;
  } catch {
    return "UTC";
  }
}

// ─── Account section ─────────────────────────────────────────────────────────

function AccountSection({
  onSignOut,
  isSigningOut,
}: {
  onSignOut: () => void;
  isSigningOut: boolean;
}) {
  const { user, refreshAuth } = useAuth();
  const { spacing, fontSize } = useResponsive();
  const [name, setName] = useState(user?.name ?? "");
  const [isSaving, setIsSaving] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const inputRef = useRef<TextInput>(null);

  useEffect(() => {
    if (user?.name && !isEditing) setName(user.name);
  }, [user?.name, isEditing]);

  const handleSaveName = useCallback(async () => {
    const trimmed = name.trim();
    if (!trimmed || trimmed === user?.name) {
      setIsEditing(false);
      return;
    }
    setIsSaving(true);
    try {
      const form = new FormData();
      form.append("name", trimmed);
      await settingsApi.updateProfile(form);
      await refreshAuth();
    } catch {
      Alert.alert("Error", "Failed to update name.");
      setName(user?.name ?? "");
    } finally {
      setIsSaving(false);
      setIsEditing(false);
    }
  }, [name, user?.name, refreshAuth]);

  return (
    <SettingsSection title="Account">
      {/* Avatar + profile summary */}
      <View
        style={{
          alignItems: "center",
          paddingTop: spacing.lg,
          paddingBottom: spacing.md,
          gap: spacing.sm,
        }}
      >
        <Avatar alt={user?.name ?? "User"} size="lg" color="accent">
          {user?.picture ? (
            <Avatar.Image source={{ uri: user.picture }} />
          ) : (
            <Avatar.Fallback>{getInitials(user?.name)}</Avatar.Fallback>
          )}
        </Avatar>
        <Text
          style={{
            fontSize: fontSize.base,
            fontWeight: "600",
            color: C.text,
          }}
        >
          {user?.name || ""}
        </Text>
        <Text style={{ fontSize: fontSize.sm, color: C.textMuted }}>
          {user?.email || ""}
        </Text>
      </View>

      <RowDivider />

      {/* Name */}
      <SettingsRow
        label="Name"
        icon={<AppIcon icon={UserCircle02Icon} size={18} color={C.primary} />}
        iconBgColor={C.primaryBg}
        stacked
      >
        {isEditing ? (
          <View style={{ gap: spacing.sm }}>
            <TextInput
              ref={inputRef}
              value={name}
              onChangeText={setName}
              autoFocus
              returnKeyType="done"
              onSubmitEditing={() => {
                void handleSaveName();
              }}
              style={{
                backgroundColor: "rgba(255,255,255,0.06)",
                borderRadius: 10,
                paddingHorizontal: spacing.md,
                paddingVertical: spacing.sm,
                fontSize: fontSize.base,
                color: C.text,
              }}
            />
            <View style={{ flexDirection: "row", gap: spacing.sm }}>
              <Pressable
                onPress={() => {
                  void handleSaveName();
                }}
                disabled={isSaving}
                style={{
                  flex: 1,
                  backgroundColor: C.primary,
                  borderRadius: 10,
                  paddingVertical: spacing.sm,
                  alignItems: "center",
                  opacity: isSaving ? 0.6 : 1,
                }}
              >
                {isSaving ? (
                  <ActivityIndicator size="small" color="#000" />
                ) : (
                  <Text
                    style={{
                      color: "#000",
                      fontWeight: "600",
                      fontSize: fontSize.sm,
                    }}
                  >
                    Save Changes
                  </Text>
                )}
              </Pressable>
              <Pressable
                onPress={() => {
                  setIsEditing(false);
                  setName(user?.name ?? "");
                }}
                style={{
                  flex: 1,
                  backgroundColor: "rgba(255,255,255,0.06)",
                  borderRadius: 10,
                  paddingVertical: spacing.sm,
                  alignItems: "center",
                }}
              >
                <Text style={{ color: C.textMuted, fontSize: fontSize.sm }}>
                  Cancel
                </Text>
              </Pressable>
            </View>
          </View>
        ) : (
          <Pressable
            onPress={() => setIsEditing(true)}
            style={{
              flexDirection: "row",
              alignItems: "center",
              justifyContent: "space-between",
              backgroundColor: "rgba(255,255,255,0.05)",
              borderRadius: 10,
              paddingHorizontal: spacing.md,
              paddingVertical: spacing.sm + 2,
            }}
          >
            <Text style={{ fontSize: fontSize.sm, color: C.text }}>
              {user?.name || "Tap to set name"}
            </Text>
            <AppIcon icon={ArrowRight01Icon} size={14} color={C.textMuted} />
          </Pressable>
        )}
      </SettingsRow>

      <RowDivider />

      {/* Email */}
      <SettingsRow
        label="Email"
        icon={<AppIcon icon={Mail01Icon} size={18} color="#a78bfa" />}
        iconBgColor="rgba(167,139,250,0.15)"
      >
        <Text
          style={{ fontSize: fontSize.sm, color: C.textMuted }}
          numberOfLines={1}
        >
          {user?.email ?? ""}
        </Text>
      </SettingsRow>

      <RowDivider />

      {/* Sign Out */}
      <SettingsRow
        label={isSigningOut ? "Signing out…" : "Sign Out"}
        description="Sign out of your account on this device"
        icon={<AppIcon icon={Logout01Icon} size={18} color={C.danger} />}
        iconBgColor={C.dangerBg}
        variant="danger"
        onPress={isSigningOut ? undefined : onSignOut}
      >
        <View
          style={{
            backgroundColor: C.dangerBg,
            borderRadius: 8,
            paddingHorizontal: 10,
            paddingVertical: 5,
            opacity: isSigningOut ? 0.6 : 1,
          }}
        >
          <Text
            style={{
              color: C.danger,
              fontSize: fontSize.xs,
              fontWeight: "600",
            }}
          >
            {isSigningOut ? "…" : "Sign out"}
          </Text>
        </View>
      </SettingsRow>
    </SettingsSection>
  );
}

// ─── Preferences section ─────────────────────────────────────────────────────

const PROFESSIONS = [
  { value: "student", label: "Student" },
  { value: "developer", label: "Software Developer" },
  { value: "designer", label: "Designer" },
  { value: "manager", label: "Manager" },
  { value: "entrepreneur", label: "Entrepreneur" },
  { value: "consultant", label: "Consultant" },
  { value: "researcher", label: "Researcher" },
  { value: "teacher", label: "Teacher" },
  { value: "writer", label: "Writer" },
  { value: "analyst", label: "Analyst" },
  { value: "engineer", label: "Engineer" },
  { value: "marketer", label: "Marketer" },
  { value: "other", label: "Other" },
];

const RESPONSE_STYLES = [
  { value: "brief", label: "Brief" },
  { value: "detailed", label: "Detailed" },
  { value: "casual", label: "Casual" },
  { value: "professional", label: "Professional" },
];

function PreferencesSection() {
  const { spacing, fontSize } = useResponsive();
  const [prefs, setPrefs] = useState<OnboardingPreferences>({});
  const [customInstructions, setCustomInstructions] = useState("");
  const [timezone] = useState(getDeviceTimezone);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);

  useEffect(() => {
    let cancelled = false;
    settingsApi
      .getProfile()
      .then((profile) => {
        if (cancelled) return;
        const p = profile.onboarding?.preferences ?? {};
        setPrefs(p);
        setCustomInstructions(p.custom_instructions ?? "");
      })
      .catch(() => {
        if (!cancelled) Alert.alert("Error", "Failed to load preferences.");
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleSave = useCallback(async () => {
    setIsSaving(true);
    try {
      await Promise.all([
        settingsApi.updatePreferences({
          ...prefs,
          custom_instructions: customInstructions.trim() || null,
        }),
        settingsApi.updateTimezone(timezone),
      ]);
      setHasUnsavedChanges(false);
      Alert.alert("Saved", "Preferences updated.");
    } catch {
      Alert.alert("Error", "Failed to save preferences.");
    } finally {
      setIsSaving(false);
    }
  }, [prefs, customInstructions, timezone]);

  if (isLoading) {
    return (
      <SettingsSection title="Preferences">
        <View style={{ alignItems: "center", paddingVertical: spacing.lg }}>
          <ActivityIndicator color={C.primary} />
        </View>
      </SettingsSection>
    );
  }

  return (
    <>
      <SettingsSection title="Preferences">
        {/* Timezone */}
        <SettingsRow
          label="Timezone"
          description="Auto-detected from your device"
          icon={<AppIcon icon={GlobeIcon} size={18} color="#34d399" />}
          iconBgColor="rgba(52,211,153,0.15)"
        >
          <Text
            style={{ fontSize: fontSize.xs, color: C.textMuted }}
            numberOfLines={1}
          >
            {timezone}
          </Text>
        </SettingsRow>

        <RowDivider />

        {/* Language */}
        <SettingsRow
          label="Language"
          description="App display language"
          icon={<AppIcon icon={TranslationIcon} size={18} color="#fb923c" />}
          iconBgColor="rgba(251,146,60,0.15)"
          showChevron
        >
          <Text style={{ fontSize: fontSize.sm, color: C.textMuted }}>
            English
          </Text>
        </SettingsRow>
      </SettingsSection>

      <SettingsSection title="Identity">
        {/* Profession */}
        <SettingsRow label="Profession" stacked>
          <View
            style={{
              flexDirection: "row",
              flexWrap: "wrap",
              gap: spacing.sm,
            }}
          >
            {PROFESSIONS.map(({ value, label }) => {
              const isActive = prefs.profession === value;
              return (
                <Pressable
                  key={value}
                  onPress={() => {
                    setPrefs((prev) => ({ ...prev, profession: value }));
                    setHasUnsavedChanges(true);
                  }}
                  style={{
                    borderRadius: 999,
                    paddingHorizontal: spacing.md,
                    paddingVertical: 6,
                    backgroundColor: isActive
                      ? C.primaryBg
                      : "rgba(255,255,255,0.06)",
                    borderWidth: 1,
                    borderColor: isActive ? C.primaryBorder : "transparent",
                  }}
                >
                  <Text
                    style={{
                      fontSize: fontSize.xs,
                      color: isActive ? C.primary : "#c5cad2",
                    }}
                  >
                    {label}
                  </Text>
                </Pressable>
              );
            })}
          </View>
        </SettingsRow>
      </SettingsSection>

      <SettingsSection title="Conversation">
        {/* Response Style */}
        <SettingsRow label="Response Style" stacked>
          <View
            style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.sm }}
          >
            {RESPONSE_STYLES.map(({ value, label }) => {
              const isActive = prefs.response_style === value;
              return (
                <Pressable
                  key={value}
                  onPress={() => {
                    setPrefs((prev) => ({
                      ...prev,
                      response_style: value,
                    }));
                    setHasUnsavedChanges(true);
                  }}
                  style={{
                    flex: 1,
                    minWidth: "40%",
                    borderRadius: 10,
                    paddingVertical: spacing.sm + 2,
                    alignItems: "center",
                    backgroundColor: isActive
                      ? C.primaryBg
                      : "rgba(255,255,255,0.06)",
                    borderWidth: 1,
                    borderColor: isActive ? C.primaryBorder : "transparent",
                  }}
                >
                  <Text
                    style={{
                      fontSize: fontSize.sm,
                      color: isActive ? C.primary : "#c5cad2",
                      fontWeight: isActive ? "600" : "400",
                    }}
                  >
                    {label}
                  </Text>
                </Pressable>
              );
            })}
          </View>
        </SettingsRow>

        <RowDivider />

        {/* Custom Instructions */}
        <SettingsRow
          label="Custom Instructions"
          description="Included in every conversation."
          stacked
        >
          <TextInput
            value={customInstructions}
            onChangeText={(text) => {
              setCustomInstructions(text);
              setHasUnsavedChanges(true);
            }}
            placeholder="Add specific instructions for how GAIA should assist you..."
            placeholderTextColor="#555"
            multiline
            numberOfLines={3}
            style={{
              backgroundColor: "rgba(255,255,255,0.06)",
              borderRadius: 12,
              paddingHorizontal: spacing.md,
              paddingVertical: spacing.md,
              fontSize: fontSize.sm,
              color: C.text,
              minHeight: 88,
              textAlignVertical: "top",
            }}
          />
        </SettingsRow>
      </SettingsSection>

      {/* Save button */}
      {hasUnsavedChanges ? (
        <Pressable
          onPress={() => {
            void handleSave();
          }}
          disabled={isSaving}
          style={{
            backgroundColor: C.primary,
            borderRadius: 12,
            paddingVertical: spacing.md,
            alignItems: "center",
            opacity: isSaving ? 0.6 : 1,
          }}
        >
          {isSaving ? (
            <ActivityIndicator color="#000" />
          ) : (
            <Text
              style={{
                color: "#000",
                fontWeight: "600",
                fontSize: fontSize.base,
              }}
            >
              Save Preferences
            </Text>
          )}
        </Pressable>
      ) : null}
    </>
  );
}

// ─── Notifications section ────────────────────────────────────────────────────

function NotificationsSection() {
  const [channels, setChannels] = useState<ChannelPreferences>({
    telegram: false,
    discord: false,
  });
  const [isLoading, setIsLoading] = useState(true);
  const [updating, setUpdating] = useState<"telegram" | "discord" | null>(null);

  useEffect(() => {
    let cancelled = false;
    settingsApi
      .getChannelPreferences()
      .then((data) => {
        if (!cancelled) setChannels(data);
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleToggle = useCallback(
    async (platform: "telegram" | "discord", enabled: boolean) => {
      setUpdating(platform);
      const prev = channels[platform];
      setChannels((c) => ({ ...c, [platform]: enabled }));
      try {
        await settingsApi.updateChannelPreference(platform, enabled);
      } catch {
        setChannels((c) => ({ ...c, [platform]: prev }));
        Alert.alert("Error", "Failed to update notification preference.");
      } finally {
        setUpdating(null);
      }
    },
    [channels],
  );

  if (isLoading) {
    return (
      <SettingsSection title="Notifications">
        <View style={{ alignItems: "center", padding: 20 }}>
          <ActivityIndicator color={C.primary} />
        </View>
      </SettingsSection>
    );
  }

  return (
    <SettingsSection
      title="Notifications"
      description="Choose where to receive GAIA notifications."
    >
      {/* Push notifications (opens OS settings) */}
      <SettingsRow
        label="Push Notifications"
        description="Device alerts and reminders"
        icon={<AppIcon icon={Notification01Icon} size={18} color="#fbbf24" />}
        iconBgColor="rgba(251,191,36,0.15)"
        showChevron
        onPress={() => {
          void Linking.openSettings();
        }}
      />

      <RowDivider />

      {/* Telegram */}
      <SettingsRow
        label="Telegram"
        description="Send notifications to this platform"
        icon={<AppIcon icon={TelegramIcon} size={18} color="#2AABEE" />}
        iconBgColor="rgba(42,171,238,0.15)"
      >
        <Switch
          value={channels.telegram}
          onValueChange={(val) => {
            void handleToggle("telegram", val);
          }}
          disabled={updating === "telegram"}
          trackColor={{ false: "#3a3a3c", true: "rgba(0,187,255,0.45)" }}
          thumbColor={channels.telegram ? C.primary : "#8e8e93"}
        />
      </SettingsRow>

      <RowDivider />

      {/* Discord */}
      <SettingsRow
        label="Discord"
        description="Send notifications to this platform"
        icon={<AppIcon icon={DiscordIcon} size={18} color="#5865F2" />}
        iconBgColor="rgba(88,101,242,0.15)"
      >
        <Switch
          value={channels.discord}
          onValueChange={(val) => {
            void handleToggle("discord", val);
          }}
          disabled={updating === "discord"}
          trackColor={{ false: "#3a3a3c", true: "rgba(0,187,255,0.45)" }}
          thumbColor={channels.discord ? C.primary : "#8e8e93"}
        />
      </SettingsRow>
    </SettingsSection>
  );
}

// ─── Usage section ────────────────────────────────────────────────────────────

function UsageSection() {
  const router = useRouter();
  const { spacing, fontSize } = useResponsive();
  const [summary, setSummary] = useState<UsageSummary | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [period, setPeriod] = useState<"day" | "month">("day");

  useEffect(() => {
    let cancelled = false;
    settingsApi
      .getUsageSummary()
      .then((data) => {
        if (!cancelled) setSummary(data);
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (isLoading) {
    return (
      <View style={{ alignItems: "center", paddingVertical: spacing.lg }}>
        <ActivityIndicator color={C.primary} />
      </View>
    );
  }

  if (!summary) {
    return (
      <SettingsSection title="Usage">
        <View style={{ padding: spacing.lg, alignItems: "center" }}>
          <Text style={{ color: C.textMuted, fontSize: fontSize.sm }}>
            No usage data available.
          </Text>
        </View>
      </SettingsSection>
    );
  }

  const featureEntries = Object.entries(summary.features).filter(
    ([, feature]) => feature.periods[period],
  );
  const isPro = summary.plan_type !== "free";
  const periodLabel = period === "day" ? "daily" : "monthly";

  const getProgressColor = (pct: number) => {
    if (pct >= 90) return C.danger;
    if (pct >= 70) return C.warning;
    return C.success;
  };

  return (
    <>
      {/* Subscription info */}
      <SettingsSection title="Subscription">
        <SettingsRow
          label="Current Plan"
          description={
            isPro
              ? "Full access to all features"
              : "Limited usage — upgrade for more"
          }
          icon={
            <AppIcon
              icon={CreditCardIcon}
              size={18}
              color={isPro ? C.primary : C.textMuted}
            />
          }
          iconBgColor={isPro ? C.primaryBg : C.iconBg}
        >
          <View
            style={{
              backgroundColor: isPro ? C.primaryBg : "rgba(255,255,255,0.06)",
              borderRadius: 999,
              paddingHorizontal: 10,
              paddingVertical: 4,
            }}
          >
            <Text
              style={{
                fontSize: fontSize.xs,
                fontWeight: "700",
                color: isPro ? C.primary : "#c5cad2",
              }}
            >
              {summary.plan_type?.toUpperCase() || "FREE"}
            </Text>
          </View>
        </SettingsRow>

        {!isPro ? (
          <>
            <RowDivider />
            <SettingsRow
              label="Upgrade to Pro"
              description="25–250x higher limits, priority support"
              icon={
                <AppIcon
                  icon={ChartLineData02Icon}
                  size={18}
                  color={C.primary}
                />
              }
              iconBgColor={C.primaryBg}
              showChevron
              onPress={() => {
                Alert.alert(
                  "Upgrade",
                  "Visit the web app to manage your subscription.",
                );
              }}
            />
          </>
        ) : null}

        <RowDivider />

        {/* Usage & Billing deep-link */}
        <SettingsRow
          label="Usage & Billing"
          description="Detailed token usage and API call history"
          icon={
            <AppIcon icon={ChartLineData02Icon} size={18} color="#fb923c" />
          }
          iconBgColor="rgba(251,146,60,0.15)"
          showChevron
          onPress={() => router.push("/settings/usage")}
        />
      </SettingsSection>

      {/* Usage section with period selector */}
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        <Text
          style={{
            fontSize: fontSize.xs,
            fontWeight: "600",
            textTransform: "uppercase",
            letterSpacing: 0.8,
            color: C.textMuted,
            paddingHorizontal: 4,
          }}
        >
          Usage
        </Text>
        <View style={{ flexDirection: "row", gap: spacing.sm }}>
          {(["day", "month"] as const).map((key) => {
            const isActive = period === key;
            return (
              <Pressable
                key={key}
                onPress={() => setPeriod(key)}
                style={{
                  borderRadius: 999,
                  paddingHorizontal: spacing.md,
                  paddingVertical: 5,
                  backgroundColor: isActive
                    ? C.primaryBg
                    : "rgba(255,255,255,0.07)",
                }}
              >
                <Text
                  style={{
                    fontSize: fontSize.xs,
                    color: isActive ? C.primary : "#c5cad2",
                    fontWeight: isActive ? "600" : "400",
                  }}
                >
                  {key === "day" ? "Daily" : "Monthly"}
                </Text>
              </Pressable>
            );
          })}
        </View>
      </View>

      <SettingsSection>
        {featureEntries.length === 0 ? (
          <View
            style={{
              padding: spacing.lg,
              alignItems: "center",
              gap: spacing.sm,
            }}
          >
            <AppIcon
              icon={ChartLineData02Icon}
              size={32}
              color={C.textSubtle}
            />
            <Text
              style={{
                fontSize: fontSize.base,
                fontWeight: "500",
                color: C.text,
                marginTop: 4,
              }}
            >
              No limits configured
            </Text>
            <Text
              style={{
                fontSize: fontSize.sm,
                color: C.textMuted,
                textAlign: "center",
              }}
            >
              No {periodLabel} limits are configured for your{" "}
              {summary.plan_type?.toUpperCase()} plan.
            </Text>
          </View>
        ) : (
          featureEntries.map(([key, feature], index) => {
            const p = feature.periods[period];
            if (!p) return null;
            const pct = Math.min(p.percentage, 100);
            return (
              <View key={key}>
                {index > 0 && <RowDivider />}
                <SettingsRow
                  label={feature.title}
                  description={feature.description}
                  stacked
                >
                  <View
                    style={{
                      flexDirection: "row",
                      alignItems: "center",
                      gap: spacing.sm,
                    }}
                  >
                    <View
                      style={{
                        flex: 1,
                        height: 5,
                        borderRadius: 3,
                        backgroundColor: "rgba(255,255,255,0.08)",
                        overflow: "hidden",
                      }}
                    >
                      <View
                        style={{
                          height: "100%",
                          width: `${pct}%`,
                          borderRadius: 3,
                          backgroundColor: getProgressColor(pct),
                        }}
                      />
                    </View>
                    <Text
                      style={{
                        fontSize: fontSize.xs,
                        color: C.textMuted,
                        flexShrink: 0,
                        minWidth: 80,
                        textAlign: "right",
                      }}
                    >
                      {p.used.toLocaleString()} / {p.limit.toLocaleString()}
                    </Text>
                  </View>
                </SettingsRow>
              </View>
            );
          })
        )}
      </SettingsSection>
    </>
  );
}

// ─── About section ────────────────────────────────────────────────────────────

function AboutSection() {
  const { fontSize } = useResponsive();
  const appVersion =
    (Constants.expoConfig?.version ?? Constants.manifest?.version) ?? "1.0.0";

  const handleLink = useCallback(async (url: string) => {
    try {
      await Linking.openURL(url);
    } catch {
      Alert.alert("Error", "Could not open link.");
    }
  }, []);

  return (
    <SettingsSection title="About">
      {/* App version */}
      <SettingsRow
        label="Version"
        icon={
          <AppIcon icon={InformationCircleIcon} size={18} color={C.textMuted} />
        }
        iconBgColor={C.iconBg}
      >
        <Text style={{ fontSize: fontSize.sm, color: C.textMuted }}>
          {appVersion}
        </Text>
      </SettingsRow>

      <RowDivider />

      {/* Contact Support */}
      <SettingsRow
        label="Contact Support"
        description="Get help from the GAIA team"
        icon={
          <AppIcon icon={CustomerSupportIcon} size={18} color="#34d399" />
        }
        iconBgColor="rgba(52,211,153,0.15)"
        showChevron
        onPress={() => {
          void handleLink("mailto:support@heygaia.io");
        }}
      />

      <RowDivider />

      {/* Privacy Policy */}
      <SettingsRow
        label="Privacy Policy"
        icon={<AppIcon icon={ShieldUserIcon} size={18} color="#818cf8" />}
        iconBgColor="rgba(129,140,248,0.15)"
        showChevron
        onPress={() => {
          void handleLink("https://heygaia.io/privacy");
        }}
      />

      <RowDivider />

      {/* Terms of Service */}
      <SettingsRow
        label="Terms of Service"
        icon={
          <AppIcon icon={DocumentAttachmentIcon} size={18} color="#94a3b8" />
        }
        iconBgColor="rgba(148,163,184,0.12)"
        showChevron
        onPress={() => {
          void handleLink("https://heygaia.io/terms");
        }}
      />
    </SettingsSection>
  );
}

// ─── Capabilities section ─────────────────────────────────────────────────────

function CapabilitiesSection() {
  const router = useRouter();
  return (
    <SettingsSection title="Capabilities">
      <SettingsRow
        label="Skills"
        icon={<AppIcon icon={FlashIcon} size={18} color="#00bbff" />}
        iconBgColor="rgba(0,187,255,0.15)"
        showChevron
        onPress={() => router.push("/skills")}
      />
      <RowDivider />
      <SettingsRow
        label="Tools"
        icon={<AppIcon icon={ToolsIcon} size={18} color="#af52de" />}
        iconBgColor="rgba(175,82,222,0.15)"
        showChevron
        onPress={() => router.push("/tools")}
      />
    </SettingsSection>
  );
}

// ─── Linked Accounts section ──────────────────────────────────────────────────

interface LinkedPlatform {
  id: string;
  name: string;
  description: string;
  icon: string;
  authType: "bot_link" | "oauth";
  botUrl?: string;
}

const LINKED_PLATFORMS: LinkedPlatform[] = [
  {
    id: "telegram",
    name: "Telegram",
    description: "Receive notifications via Telegram bot",
    icon: "https://upload.wikimedia.org/wikipedia/commons/thumb/8/83/Telegram_2019_Logo.svg/120px-Telegram_2019_Logo.svg.png",
    authType: "bot_link",
    botUrl: "https://t.me/gaia_assistant_bot",
  },
  {
    id: "discord",
    name: "Discord",
    description: "Receive notifications via Discord bot",
    icon: "https://assets-global.slack.com/marketing-api/assets/img/icons/icon_app_home.png",
    authType: "oauth",
  },
  {
    id: "slack",
    name: "Slack",
    description: "Receive notifications via Slack",
    icon: "https://a.slack-edge.com/80588/marketing/img/meta/slack_hash_128.png",
    authType: "oauth",
  },
];

function LinkedAccountsSection() {
  const { spacing, fontSize } = useResponsive();
  const [linkedPlatforms, setLinkedPlatforms] = useState<
    Record<string, boolean>
  >({});

  const handleConnect = useCallback(async (platform: LinkedPlatform) => {
    if (platform.authType === "bot_link" && platform.botUrl) {
      try {
        await Linking.openURL(platform.botUrl);
      } catch {
        Alert.alert("Error", "Could not open link.");
      }
      return;
    }
    // OAuth flow — placeholder for future implementation
    Alert.alert(
      "Connect",
      `OAuth connection for ${platform.name} will be available soon.`,
    );
  }, []);

  const handleDisconnect = useCallback((platformId: string) => {
    setLinkedPlatforms((prev) => ({ ...prev, [platformId]: false }));
  }, []);

  return (
    <SettingsSection
      title="Linked Accounts"
      description="Connect your accounts to receive notifications and enable automations."
    >
      {LINKED_PLATFORMS.map((platform, index) => {
        const isLinked = linkedPlatforms[platform.id] ?? false;
        return (
          <View key={platform.id}>
            {index > 0 && <RowDivider />}
            <SettingsRow
              label={platform.name}
              description={platform.description}
              icon={
                <Image
                  source={{ uri: platform.icon }}
                  style={{ width: 20, height: 20 }}
                  resizeMode="contain"
                />
              }
            >
              <Pressable
                onPress={() =>
                  isLinked
                    ? handleDisconnect(platform.id)
                    : void handleConnect(platform)
                }
                style={{
                  paddingHorizontal: 12,
                  paddingVertical: 5,
                  borderRadius: 8,
                  backgroundColor: isLinked
                    ? C.dangerBg
                    : C.primaryBg,
                  borderWidth: 1,
                  borderColor: isLinked
                    ? "rgba(239,68,68,0.3)"
                    : C.primaryBorder,
                }}
              >
                <Text
                  style={{
                    fontSize: fontSize.xs,
                    fontWeight: "600",
                    color: isLinked ? C.danger : C.primary,
                  }}
                >
                  {isLinked ? "Disconnect" : "Connect"}
                </Text>
              </Pressable>
            </SettingsRow>
          </View>
        );
      })}
    </SettingsSection>
  );
}

// ─── Memory section ───────────────────────────────────────────────────────────

function MemorySection() {
  const router = useRouter();
  return (
    <SettingsSection title="Memory">
      <SettingsRow
        label="Memory"
        description="View and manage what GAIA remembers"
        icon={<AppIcon icon={BrainIcon} size={18} color="#00bbff" />}
        iconBgColor="rgba(0,187,255,0.15)"
        showChevron
        onPress={() => router.push("/memory")}
      />
    </SettingsSection>
  );
}


// ─── Appearance section ───────────────────────────────────────────────────────

const THEME_OPTIONS: { value: ThemeMode; label: string }[] = [
  { value: "light", label: "Light" },
  { value: "system", label: "System" },
  { value: "dark", label: "Dark" },
];

function AppearanceSection() {
  const { spacing, fontSize } = useResponsive();
  const mode = useThemeStore((s) => s.mode);
  const setMode = useThemeStore((s) => s.setMode);

  return (
    <SettingsSection title="Appearance">
      <SettingsRow label="Theme" stacked>
        <View style={{ flexDirection: "row", gap: spacing.xs }}>
          {THEME_OPTIONS.map(({ value, label }) => {
            const isActive = mode === value;
            return (
              <Pressable
                key={value}
                onPress={() => setMode(value)}
                style={{
                  flex: 1,
                  paddingVertical: spacing.sm,
                  alignItems: "center",
                  borderRadius: 10,
                  backgroundColor: isActive
                    ? C.primaryBg
                    : "rgba(255,255,255,0.05)",
                  borderWidth: 1,
                  borderColor: isActive ? C.primaryBorder : "transparent",
                }}
              >
                <Text
                  style={{
                    fontSize: fontSize.xs,
                    color: isActive ? C.primary : C.textMuted,
                    fontWeight: isActive ? "600" : "400",
                  }}
                >
                  {label}
                </Text>
              </Pressable>
            );
          })}
        </View>
      </SettingsRow>
    </SettingsSection>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function SettingsScreen() {
  const router = useRouter();
  const { signOut } = useAuth();
  const { spacing, fontSize } = useResponsive();
  const insets = useSafeAreaInsets();
  const [isSigningOut, setIsSigningOut] = useState(false);

  const handleSignOut = useCallback(async () => {
    Alert.alert("Sign Out", "Are you sure you want to sign out?", [
      { text: "Cancel", style: "cancel" },
      {
        text: "Sign Out",
        style: "destructive",
        onPress: async () => {
          setIsSigningOut(true);
          try {
            await signOut();
            router.replace("/login");
          } catch (error) {
            console.error("Sign out error:", error);
          } finally {
            setIsSigningOut(false);
          }
        },
      },
    ]);
  }, [signOut, router]);

  return (
    <View style={{ flex: 1, backgroundColor: C.bg }}>
      {/* Header */}
      <View
        style={{
          paddingTop: insets.top + spacing.sm,
          paddingHorizontal: spacing.md,
          paddingBottom: spacing.md,
          borderBottomWidth: 1,
          borderBottomColor: C.divider,
          flexDirection: "row",
          alignItems: "center",
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
          <AppIcon icon={ArrowLeft01Icon} size={18} color={C.text} />
        </Pressable>
        <Text
          style={{
            marginLeft: spacing.md,
            fontSize: fontSize.base,
            fontWeight: "600",
            color: C.text,
            flex: 1,
          }}
        >
          Settings
        </Text>
      </View>

      <ScrollView
        showsVerticalScrollIndicator={false}
        keyboardShouldPersistTaps="handled"
        contentContainerStyle={{
          paddingBottom: insets.bottom + spacing.lg,
          paddingTop: spacing.lg,
        }}
      >
        <SettingsPage>
          {/* Account — profile photo, name, email, logout */}
          <AccountSection
            onSignOut={() => {
              void handleSignOut();
            }}
            isSigningOut={isSigningOut}
          />

          {/* Appearance — light/dark/system theme toggle */}
          <AppearanceSection />

          {/* Preferences — timezone, language, identity, conversation */}
          <PreferencesSection />

          {/* Notifications — push, telegram, discord */}
          <NotificationsSection />

          {/* Linked Accounts — telegram, discord, slack */}
          <LinkedAccountsSection />

          {/* Capabilities — skills and tools */}
          <CapabilitiesSection />

          {/* Memory — view, search, add and delete memories */}
          <MemorySection />

          {/* Usage — subscription info + API usage stats */}
          <UsageSection />

          {/* About — version, privacy policy, terms */}
          <AboutSection />
        </SettingsPage>
      </ScrollView>
    </View>
  );
}
