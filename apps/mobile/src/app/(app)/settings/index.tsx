import { useRouter } from "expo-router";
import { Avatar } from "heroui-native";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  ScrollView,
  Switch,
  TextInput,
  View,
} from "react-native";
import {
  ArrowLeft01Icon,
  BrainIcon,
  ChartLineData01Icon,
  DiscordIcon,
  HugeiconsIcon,
  Logout01Icon,
  Settings02Icon,
  TelegramIcon,
  UserCircleIcon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useAuth } from "@/features/auth";
import type {
  ChannelPreferences,
  OnboardingPreferences,
  UsageSummary,
} from "@/features/settings/api/settings-api";
import { settingsApi } from "@/features/settings/api/settings-api";
import { useResponsive } from "@/lib/responsive";

// ─── Helpers ────────────────────────────────────────────────────────────────

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

// ─── Sub-components ──────────────────────────────────────────────────────────

function SectionTitle({ children }: { children: string }) {
  const { spacing, fontSize } = useResponsive();
  return (
    <Text
      style={{
        fontSize: fontSize.xs,
        color: "#8e8e93",
        textTransform: "uppercase",
        letterSpacing: 1,
        paddingHorizontal: spacing.md,
        marginBottom: spacing.xs,
        marginTop: spacing.lg,
      }}
    >
      {children}
    </Text>
  );
}

function Divider() {
  return (
    <View
      style={{
        height: 1,
        backgroundColor: "rgba(255,255,255,0.06)",
        marginLeft: 56,
      }}
    />
  );
}

interface RowProps {
  icon?: React.ReactNode;
  label: string;
  value?: string;
  onPress?: () => void;
  right?: React.ReactNode;
  labelColor?: string;
  showChevron?: boolean;
}

function Row({
  icon,
  label,
  value,
  onPress,
  right,
  labelColor,
  showChevron = false,
}: RowProps) {
  const { spacing, fontSize } = useResponsive();
  return (
    <Pressable
      onPress={onPress}
      disabled={!onPress}
      style={({ pressed }) => ({
        flexDirection: "row",
        alignItems: "center",
        paddingHorizontal: spacing.md,
        paddingVertical: 13,
        backgroundColor:
          pressed && onPress ? "rgba(255,255,255,0.04)" : "transparent",
        gap: 12,
      })}
    >
      {icon ? (
        <View
          style={{
            width: 32,
            height: 32,
            borderRadius: 8,
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          {icon}
        </View>
      ) : null}
      <Text
        style={{
          flex: 1,
          fontSize: fontSize.base,
          color: labelColor ?? "#e8ebef",
        }}
      >
        {label}
      </Text>
      {value ? (
        <Text style={{ fontSize: fontSize.sm, color: "#8e8e93" }}>{value}</Text>
      ) : null}
      {right}
      {showChevron && <Text style={{ color: "#48484a", fontSize: 16 }}>›</Text>}
    </Pressable>
  );
}

function Card({ children }: { children: React.ReactNode }) {
  const { spacing } = useResponsive();
  return (
    <View
      style={{
        backgroundColor: "#1c1c1e",
        borderRadius: 12,
        marginHorizontal: spacing.md,
        overflow: "hidden",
      }}
    >
      {children}
    </View>
  );
}

// ─── Account card at top ─────────────────────────────────────────────────────

function AccountCard() {
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
    <View
      style={{
        marginHorizontal: spacing.md,
        backgroundColor: "#1c1c1e",
        borderRadius: 16,
        padding: spacing.lg,
        alignItems: "center",
        gap: spacing.md,
      }}
    >
      <Avatar alt={user?.name ?? "User"} size="lg" color="accent">
        {user?.picture ? (
          <Avatar.Image source={{ uri: user.picture }} />
        ) : (
          <Avatar.Fallback>{getInitials(user?.name)}</Avatar.Fallback>
        )}
      </Avatar>

      {isEditing ? (
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            gap: spacing.sm,
            width: "100%",
          }}
        >
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
              flex: 1,
              backgroundColor: "#2c2c2e",
              borderRadius: 8,
              paddingHorizontal: spacing.md,
              paddingVertical: spacing.sm,
              fontSize: fontSize.base,
              color: "#fff",
              textAlign: "center",
            }}
          />
          <Pressable
            onPress={() => {
              void handleSaveName();
            }}
            disabled={isSaving}
            style={{
              backgroundColor: "#16c1ff",
              borderRadius: 8,
              paddingHorizontal: spacing.md,
              paddingVertical: spacing.sm,
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
                Save
              </Text>
            )}
          </Pressable>
          <Pressable
            onPress={() => {
              setIsEditing(false);
              setName(user?.name ?? "");
            }}
            style={{ paddingHorizontal: spacing.sm }}
          >
            <Text style={{ color: "#8e8e93", fontSize: fontSize.sm }}>
              Cancel
            </Text>
          </Pressable>
        </View>
      ) : (
        <Pressable onPress={() => setIsEditing(true)}>
          <Text
            style={{
              fontSize: fontSize.base,
              fontWeight: "600",
              color: "#e8ebef",
            }}
          >
            {user?.name ?? "User"}
          </Text>
          <Text
            style={{
              fontSize: fontSize.xs,
              color: "#8e8e93",
              textAlign: "center",
              marginTop: 2,
            }}
          >
            Tap to edit name
          </Text>
        </Pressable>
      )}

      <Text style={{ fontSize: fontSize.sm, color: "#8e8e93" }}>
        {user?.email ?? ""}
      </Text>
    </View>
  );
}

// ─── Preferences inline ───────────────────────────────────────────────────────

const PROFESSIONS = [
  "Software Engineer",
  "Product Manager",
  "Designer",
  "Data Scientist",
  "Marketing",
  "Student",
  "Other",
];

const RESPONSE_STYLES: { value: string; label: string }[] = [
  { value: "concise", label: "Concise" },
  { value: "detailed", label: "Detailed" },
  { value: "balanced", label: "Balanced" },
];

function PreferencesCard() {
  const { spacing, fontSize } = useResponsive();
  const [prefs, setPrefs] = useState<OnboardingPreferences>({});
  const [customInstructions, setCustomInstructions] = useState("");
  const [timezone] = useState(getDeviceTimezone);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);

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
      Alert.alert("Saved", "Preferences updated.");
    } catch {
      Alert.alert("Error", "Failed to save preferences.");
    } finally {
      setIsSaving(false);
    }
  }, [prefs, customInstructions, timezone]);

  if (isLoading) {
    return (
      <View style={{ alignItems: "center", paddingVertical: spacing.lg }}>
        <ActivityIndicator color="#16c1ff" />
      </View>
    );
  }

  return (
    <View style={{ marginHorizontal: spacing.md, gap: spacing.md }}>
      {/* Profession */}
      <View style={{ gap: spacing.sm }}>
        <Text
          style={{ fontSize: fontSize.xs, color: "#8e8e93", paddingLeft: 4 }}
        >
          Profession
        </Text>
        <View
          style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.sm }}
        >
          {PROFESSIONS.map((p) => {
            const isActive = prefs.profession === p;
            return (
              <Pressable
                key={p}
                onPress={() => setPrefs((prev) => ({ ...prev, profession: p }))}
                style={{
                  borderRadius: 999,
                  paddingHorizontal: spacing.md,
                  paddingVertical: 6,
                  backgroundColor: isActive
                    ? "rgba(22,193,255,0.2)"
                    : "#1c1c1e",
                  borderWidth: 1,
                  borderColor: isActive
                    ? "rgba(22,193,255,0.5)"
                    : "transparent",
                }}
              >
                <Text
                  style={{
                    fontSize: fontSize.sm,
                    color: isActive ? "#9fe6ff" : "#c5cad2",
                  }}
                >
                  {p}
                </Text>
              </Pressable>
            );
          })}
        </View>
      </View>

      {/* Response style */}
      <View style={{ gap: spacing.sm }}>
        <Text
          style={{ fontSize: fontSize.xs, color: "#8e8e93", paddingLeft: 4 }}
        >
          Response Style
        </Text>
        <View style={{ flexDirection: "row", gap: spacing.sm }}>
          {RESPONSE_STYLES.map(({ value, label }) => {
            const isActive = prefs.response_style === value;
            return (
              <Pressable
                key={value}
                onPress={() =>
                  setPrefs((prev) => ({ ...prev, response_style: value }))
                }
                style={{
                  flex: 1,
                  borderRadius: 10,
                  paddingVertical: spacing.md,
                  alignItems: "center",
                  backgroundColor: isActive
                    ? "rgba(22,193,255,0.2)"
                    : "#1c1c1e",
                  borderWidth: 1,
                  borderColor: isActive
                    ? "rgba(22,193,255,0.5)"
                    : "transparent",
                }}
              >
                <Text
                  style={{
                    fontSize: fontSize.sm,
                    color: isActive ? "#9fe6ff" : "#c5cad2",
                    fontWeight: isActive ? "600" : "400",
                  }}
                >
                  {label}
                </Text>
              </Pressable>
            );
          })}
        </View>
      </View>

      {/* Custom instructions */}
      <View style={{ gap: spacing.sm }}>
        <Text
          style={{ fontSize: fontSize.xs, color: "#8e8e93", paddingLeft: 4 }}
        >
          Custom Instructions
        </Text>
        <TextInput
          value={customInstructions}
          onChangeText={setCustomInstructions}
          placeholder="Tell GAIA how you'd like it to respond…"
          placeholderTextColor="#555"
          multiline
          numberOfLines={3}
          style={{
            backgroundColor: "#1c1c1e",
            borderRadius: 10,
            paddingHorizontal: spacing.md,
            paddingVertical: spacing.md,
            fontSize: fontSize.sm,
            color: "#fff",
            minHeight: 88,
            textAlignVertical: "top",
          }}
        />
      </View>

      {/* Timezone display */}
      <Row label="Timezone" value={timezone} />

      {/* Save */}
      <Pressable
        onPress={() => {
          void handleSave();
        }}
        disabled={isSaving}
        style={{
          backgroundColor: "#16c1ff",
          borderRadius: 10,
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
    </View>
  );
}

// ─── Notifications toggles ────────────────────────────────────────────────────

function NotificationsCard() {
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
      <Card>
        <View style={{ alignItems: "center", padding: 20 }}>
          <ActivityIndicator color="#16c1ff" />
        </View>
      </Card>
    );
  }

  return (
    <Card>
      <Row
        icon={<HugeiconsIcon icon={TelegramIcon} size={20} color="#2AABEE" />}
        label="Telegram"
        right={
          <Switch
            value={channels.telegram}
            onValueChange={(val) => {
              void handleToggle("telegram", val);
            }}
            disabled={updating === "telegram"}
            trackColor={{ false: "#3a3a3c", true: "rgba(22,193,255,0.6)" }}
            thumbColor={channels.telegram ? "#16c1ff" : "#8e8e93"}
          />
        }
      />
      <Divider />
      <Row
        icon={<HugeiconsIcon icon={DiscordIcon} size={20} color="#5865F2" />}
        label="Discord"
        right={
          <Switch
            value={channels.discord}
            onValueChange={(val) => {
              void handleToggle("discord", val);
            }}
            disabled={updating === "discord"}
            trackColor={{ false: "#3a3a3c", true: "rgba(22,193,255,0.6)" }}
            thumbColor={channels.discord ? "#16c1ff" : "#8e8e93"}
          />
        }
      />
    </Card>
  );
}

// ─── Usage card ───────────────────────────────────────────────────────────────

function UsageCard() {
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
      <Card>
        <View style={{ alignItems: "center", padding: 20 }}>
          <ActivityIndicator color="#16c1ff" />
        </View>
      </Card>
    );
  }

  if (!summary) {
    return (
      <Card>
        <View style={{ padding: 20 }}>
          <Text style={{ color: "#8e8e93", fontSize: fontSize.sm }}>
            No usage data available.
          </Text>
        </View>
      </Card>
    );
  }

  const entries = Object.entries(summary.features);
  const isPro = summary.plan_type !== "free";

  return (
    <View style={{ marginHorizontal: spacing.md, gap: spacing.md }}>
      {/* Plan row */}
      <View
        style={{
          backgroundColor: "#1c1c1e",
          borderRadius: 12,
          paddingHorizontal: spacing.md,
          paddingVertical: spacing.md,
          flexDirection: "row",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        <View>
          <Text style={{ fontSize: fontSize.xs, color: "#8e8e93" }}>
            Current Plan
          </Text>
          <Text
            style={{
              fontSize: fontSize.base,
              fontWeight: "600",
              color: "#e8ebef",
              marginTop: 2,
            }}
          >
            {isPro ? "Pro" : "Free"}
          </Text>
        </View>
        {!isPro && (
          <View
            style={{
              backgroundColor: "#16c1ff",
              borderRadius: 8,
              paddingHorizontal: spacing.md,
              paddingVertical: 6,
            }}
          >
            <Text
              style={{
                color: "#000",
                fontWeight: "700",
                fontSize: fontSize.sm,
              }}
            >
              Upgrade
            </Text>
          </View>
        )}
      </View>

      {/* Period picker */}
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
                paddingVertical: 6,
                backgroundColor: isActive ? "rgba(22,193,255,0.2)" : "#1c1c1e",
                borderWidth: 1,
                borderColor: isActive ? "rgba(22,193,255,0.4)" : "transparent",
              }}
            >
              <Text
                style={{
                  fontSize: fontSize.sm,
                  color: isActive ? "#9fe6ff" : "#c5cad2",
                  fontWeight: isActive ? "600" : "400",
                }}
              >
                {key === "day" ? "Daily" : "Monthly"}
              </Text>
            </Pressable>
          );
        })}
      </View>

      {/* Feature bars */}
      {entries.length > 0 && (
        <View
          style={{
            backgroundColor: "#1c1c1e",
            borderRadius: 12,
            padding: spacing.md,
            gap: spacing.lg,
          }}
        >
          {entries.map(([key, feature]) => {
            const p = feature.periods[period];
            if (!p) return null;
            const pct = Math.min(p.percentage, 100);
            const barColor =
              pct >= 90 ? "#ef4444" : pct >= 70 ? "#f59e0b" : "#16c1ff";
            return (
              <View key={key} style={{ gap: 6 }}>
                <View
                  style={{
                    flexDirection: "row",
                    justifyContent: "space-between",
                  }}
                >
                  <Text style={{ fontSize: fontSize.sm, color: "#e8ebef" }}>
                    {feature.title}
                  </Text>
                  <Text style={{ fontSize: fontSize.xs, color: "#8e8e93" }}>
                    {p.used} / {p.limit}
                  </Text>
                </View>
                <View
                  style={{
                    height: 6,
                    borderRadius: 3,
                    backgroundColor: "rgba(255,255,255,0.1)",
                    overflow: "hidden",
                  }}
                >
                  <View
                    style={{
                      height: "100%",
                      width: `${pct}%`,
                      borderRadius: 3,
                      backgroundColor: barColor,
                    }}
                  />
                </View>
                <Text style={{ fontSize: fontSize.xs - 1, color: "#5a5a5e" }}>
                  {p.remaining} remaining
                  {p.reset_time
                    ? ` · resets ${new Date(p.reset_time).toLocaleDateString()}`
                    : ""}
                </Text>
              </View>
            );
          })}
        </View>
      )}
    </View>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function SettingsScreen() {
  const router = useRouter();
  const { signOut } = useAuth();
  const { spacing, fontSize } = useResponsive();
  const [isSigningOut, setIsSigningOut] = useState(false);

  const handleSignOut = useCallback(async () => {
    Alert.alert("Sign Out", "Are you sure you want to sign out?", [
      { text: "Cancel", style: "cancel" },
      {
        text: "Sign Out",
        style: "destructive",
        onPress: async () => {
          setIsSigningOut(true);
          await signOut();
          router.replace("/login");
        },
      },
    ]);
  }, [signOut, router]);

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
          <HugeiconsIcon icon={ArrowLeft01Icon} size={18} color="#fff" />
        </Pressable>
        <Text
          style={{
            marginLeft: spacing.md,
            fontSize: fontSize.base,
            fontWeight: "600",
            color: "#fff",
            flex: 1,
          }}
        >
          Settings
        </Text>
      </View>

      <ScrollView
        showsVerticalScrollIndicator={false}
        keyboardShouldPersistTaps="handled"
        contentContainerStyle={{ paddingBottom: 60, paddingTop: spacing.lg }}
      >
        {/* ── Account ── */}
        <AccountCard />

        {/* ── Preferences ── */}
        <SectionTitle>Preferences</SectionTitle>
        <Card>
          <Row
            icon={
              <View
                style={{
                  backgroundColor: "rgba(99,102,241,0.2)",
                  borderRadius: 8,
                  width: 32,
                  height: 32,
                  alignItems: "center",
                  justifyContent: "center",
                }}
              >
                <HugeiconsIcon
                  icon={UserCircleIcon}
                  size={18}
                  color="#818cf8"
                />
              </View>
            }
            label="Profile & AI settings"
            showChevron
            onPress={() => {}}
          />
        </Card>

        <View style={{ marginTop: spacing.md }}>
          <PreferencesCard />
        </View>

        {/* ── Notifications ── */}
        <SectionTitle>Notifications</SectionTitle>
        <NotificationsCard />

        {/* ── Usage ── */}
        <SectionTitle>Usage</SectionTitle>
        <Card>
          <Row
            icon={
              <View
                style={{
                  backgroundColor: "rgba(22,193,255,0.12)",
                  borderRadius: 8,
                  width: 32,
                  height: 32,
                  alignItems: "center",
                  justifyContent: "center",
                }}
              >
                <HugeiconsIcon
                  icon={ChartLineData01Icon}
                  size={18}
                  color="#16c1ff"
                />
              </View>
            }
            label="Usage & Limits"
          />
        </Card>
        <View style={{ marginTop: spacing.md }}>
          <UsageCard />
        </View>

        {/* ── Memories ── */}
        <SectionTitle>Memory</SectionTitle>
        <Card>
          <Row
            icon={
              <View
                style={{
                  backgroundColor: "rgba(168,85,247,0.15)",
                  borderRadius: 8,
                  width: 32,
                  height: 32,
                  alignItems: "center",
                  justifyContent: "center",
                }}
              >
                <HugeiconsIcon icon={BrainIcon} size={18} color="#a855f7" />
              </View>
            }
            label="Memories"
            value="Manage"
            showChevron
            onPress={() => {}}
          />
        </Card>

        {/* ── Customization ── */}
        <SectionTitle>Customization</SectionTitle>
        <Card>
          <Row
            icon={
              <View
                style={{
                  backgroundColor: "rgba(251,191,36,0.12)",
                  borderRadius: 8,
                  width: 32,
                  height: 32,
                  alignItems: "center",
                  justifyContent: "center",
                }}
              >
                <HugeiconsIcon
                  icon={Settings02Icon}
                  size={18}
                  color="#fbbf24"
                />
              </View>
            }
            label="Appearance"
            showChevron
            onPress={() => {}}
          />
        </Card>

        {/* ── Sign Out ── */}
        <View style={{ marginTop: spacing.xl, marginHorizontal: spacing.md }}>
          <Pressable
            onPress={() => {
              void handleSignOut();
            }}
            disabled={isSigningOut}
            style={{
              flexDirection: "row",
              alignItems: "center",
              gap: 12,
              backgroundColor: "rgba(239,68,68,0.08)",
              borderRadius: 12,
              paddingHorizontal: spacing.md,
              paddingVertical: 14,
              opacity: isSigningOut ? 0.6 : 1,
            }}
          >
            <HugeiconsIcon icon={Logout01Icon} size={20} color="#ef4444" />
            <Text style={{ color: "#ef4444", fontSize: fontSize.base }}>
              {isSigningOut ? "Signing out…" : "Sign Out"}
            </Text>
          </Pressable>
        </View>
      </ScrollView>
    </View>
  );
}
