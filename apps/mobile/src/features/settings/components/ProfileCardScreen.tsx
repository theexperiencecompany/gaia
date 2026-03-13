import * as Clipboard from "expo-clipboard";
import { useRouter } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Image,
  Pressable,
  ScrollView,
  Share,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import {
  AppIcon,
  ArrowLeft01Icon,
  Copy01Icon,
  Share01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import type {
  HoloCardColors,
  UserProfile,
  UserStats,
} from "@/features/settings/api/settings-api";
import { settingsApi } from "@/features/settings/api/settings-api";
import { useResponsive } from "@/lib/responsive";

// ─── Color tokens ─────────────────────────────────────────────────────────────
const C = {
  bg: "#0b0c0f",
  cardBg: "#131416",
  surface: "#1a1c21",
  divider: "rgba(255,255,255,0.06)",
  text: "#ffffff",
  textMuted: "#8e8e93",
  textSubtle: "#5a5a5e",
  primary: "#00bbff",
  primaryBg: "rgba(0,187,255,0.15)",
};

// ─── Preset accent colors ─────────────────────────────────────────────────────
const ACCENT_PRESETS: HoloCardColors[] = [
  { accent: "#00bbff", gradient_from: "#003d54", gradient_to: "#001a2b" },
  { accent: "#a855f7", gradient_from: "#3b0764", gradient_to: "#1a0030" },
  { accent: "#22c55e", gradient_from: "#052e16", gradient_to: "#001a0d" },
  { accent: "#f59e0b", gradient_from: "#451a03", gradient_to: "#1a0800" },
  { accent: "#ef4444", gradient_from: "#450a0a", gradient_to: "#1a0303" },
  { accent: "#ec4899", gradient_from: "#500724", gradient_to: "#1a0010" },
];

// ─── Helpers ──────────────────────────────────────────────────────────────────

function getInitials(name?: string): string {
  if (!name) return "U";
  const parts = name.trim().split(" ");
  if (parts.length >= 2) {
    return `${parts[0][0]}${parts[parts.length - 1][0]}`.toUpperCase();
  }
  return name[0].toUpperCase();
}

function formatMemberSince(dateStr?: string): string {
  if (!dateStr) return "Early member";
  try {
    const date = new Date(dateStr);
    return `Member since ${date.toLocaleDateString("en-US", {
      month: "long",
      year: "numeric",
    })}`;
  } catch {
    return "Early member";
  }
}

// ─── Profile Card Visual ──────────────────────────────────────────────────────

interface ProfileCardProps {
  profile: UserProfile;
  stats: UserStats | null;
  accentColors: HoloCardColors;
}

function ProfileCard({ profile, stats, accentColors }: ProfileCardProps) {
  const { spacing, fontSize } = useResponsive();
  const avatarUri = profile.picture;
  const initials = getInitials(profile.name);

  return (
    <View
      style={{
        borderRadius: 20,
        overflow: "hidden",
        borderWidth: 1,
        borderColor: `${accentColors.accent}33`,
        shadowColor: accentColors.accent,
        shadowOffset: { width: 0, height: 8 },
        shadowOpacity: 0.25,
        shadowRadius: 20,
        elevation: 12,
      }}
    >
      {/* Card background gradient simulation via layered views */}
      <View
        style={{
          backgroundColor: accentColors.gradient_from,
          padding: spacing.lg,
          paddingBottom: spacing.md,
        }}
      >
        {/* Top accent bar */}
        <View
          style={{
            height: 3,
            backgroundColor: accentColors.accent,
            borderRadius: 2,
            marginBottom: spacing.lg,
            opacity: 0.8,
          }}
        />

        {/* Avatar + name row */}
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            gap: spacing.md,
            marginBottom: spacing.md,
          }}
        >
          <View
            style={{
              width: 64,
              height: 64,
              borderRadius: 32,
              backgroundColor: `${accentColors.accent}22`,
              alignItems: "center",
              justifyContent: "center",
              borderWidth: 2,
              borderColor: `${accentColors.accent}66`,
              overflow: "hidden",
            }}
          >
            {avatarUri ? (
              <Image
                source={{ uri: avatarUri }}
                style={{ width: 64, height: 64, borderRadius: 32 }}
                resizeMode="cover"
              />
            ) : (
              <Text
                style={{
                  fontSize: 22,
                  fontWeight: "700",
                  color: accentColors.accent,
                }}
              >
                {initials}
              </Text>
            )}
          </View>

          <View style={{ flex: 1 }}>
            <Text
              style={{
                fontSize: fontSize["2xl"],
                fontWeight: "700",
                color: C.text,
                letterSpacing: -0.5,
              }}
              numberOfLines={1}
            >
              {profile.name}
            </Text>
            <Text
              style={{
                fontSize: fontSize.sm,
                color: C.textMuted,
                marginTop: 2,
              }}
              numberOfLines={1}
            >
              {profile.email}
            </Text>
          </View>
        </View>

        {/* Member since */}
        <Text
          style={{
            fontSize: fontSize.xs,
            color: accentColors.accent,
            fontWeight: "600",
            letterSpacing: 0.5,
            marginBottom: spacing.md,
          }}
        >
          {formatMemberSince(profile.created_at)}
        </Text>

        {/* Divider */}
        <View
          style={{
            height: 1,
            backgroundColor: `${accentColors.accent}22`,
            marginBottom: spacing.md,
          }}
        />

        {/* Stats row */}
        {stats ? (
          <View
            style={{
              flexDirection: "row",
              justifyContent: "space-around",
            }}
          >
            <View style={{ alignItems: "center" }}>
              <Text
                style={{
                  fontSize: fontSize["2xl"],
                  fontWeight: "700",
                  color: accentColors.accent,
                }}
              >
                {stats.conversation_count}
              </Text>
              <Text style={{ fontSize: fontSize.xs, color: C.textMuted }}>
                Conversations
              </Text>
            </View>
            <View
              style={{
                width: 1,
                backgroundColor: `${accentColors.accent}22`,
              }}
            />
            <View style={{ alignItems: "center" }}>
              <Text
                style={{
                  fontSize: fontSize["2xl"],
                  fontWeight: "700",
                  color: accentColors.accent,
                }}
              >
                {stats.workflow_count}
              </Text>
              <Text style={{ fontSize: fontSize.xs, color: C.textMuted }}>
                Workflows
              </Text>
            </View>
            <View
              style={{
                width: 1,
                backgroundColor: `${accentColors.accent}22`,
              }}
            />
            <View style={{ alignItems: "center" }}>
              <Text
                style={{
                  fontSize: fontSize["2xl"],
                  fontWeight: "700",
                  color: accentColors.accent,
                }}
              >
                {stats.integration_count}
              </Text>
              <Text style={{ fontSize: fontSize.xs, color: C.textMuted }}>
                Integrations
              </Text>
            </View>
          </View>
        ) : (
          <View style={{ height: 40, justifyContent: "center" }}>
            <ActivityIndicator size="small" color={accentColors.accent} />
          </View>
        )}
      </View>

      {/* Footer strip */}
      <View
        style={{
          backgroundColor: accentColors.gradient_to,
          paddingHorizontal: spacing.lg,
          paddingVertical: spacing.sm,
          flexDirection: "row",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        <Text
          style={{
            fontSize: fontSize.xs,
            color: C.textSubtle,
            fontWeight: "600",
            letterSpacing: 1.5,
            textTransform: "uppercase",
          }}
        >
          GAIA
        </Text>
        <View
          style={{
            width: 24,
            height: 24,
            borderRadius: 12,
            backgroundColor: `${accentColors.accent}33`,
            borderWidth: 1,
            borderColor: `${accentColors.accent}55`,
          }}
        />
      </View>
    </View>
  );
}

// ─── Main Screen ──────────────────────────────────────────────────────────────

export function ProfileCardScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { spacing, fontSize } = useResponsive();

  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [stats, setStats] = useState<UserStats | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSavingColors, setIsSavingColors] = useState(false);
  const [selectedColors, setSelectedColors] = useState<HoloCardColors>(
    ACCENT_PRESETS[0],
  );

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);

    Promise.all([settingsApi.getProfile(), settingsApi.getUserStats()])
      .then(([profileData, statsData]) => {
        if (cancelled) return;
        setProfile(profileData);
        setStats(statsData);
      })
      .catch(() => {
        if (!cancelled) Alert.alert("Error", "Failed to load profile.");
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const handleSelectColor = useCallback(async (colors: HoloCardColors) => {
    setSelectedColors(colors);
    setIsSavingColors(true);
    try {
      await settingsApi.updateHoloCardColors(colors);
    } catch {
      // Non-fatal: color preference failed to persist but UI already updated
    } finally {
      setIsSavingColors(false);
    }
  }, []);

  const handleShareProfile = useCallback(async () => {
    if (!profile) return;
    const profileUrl = `https://heygaia.io/u/${profile.user_id}`;
    try {
      await Share.share({
        message: `Check out ${profile.name}'s GAIA profile: ${profileUrl}`,
        url: profileUrl,
      });
    } catch {
      // User dismissed share sheet — no action needed
    }
  }, [profile]);

  const handleCopyLink = useCallback(async () => {
    if (!profile) return;
    const profileUrl = `https://heygaia.io/u/${profile.user_id}`;
    try {
      await Clipboard.setStringAsync(profileUrl);
      Alert.alert("Copied", "Profile link copied to clipboard.");
    } catch {
      Alert.alert("Error", "Failed to copy link.");
    }
  }, [profile]);

  if (isLoading) {
    return (
      <View
        style={{
          flex: 1,
          backgroundColor: C.bg,
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <ActivityIndicator color={C.primary} />
      </View>
    );
  }

  if (!profile) {
    return (
      <View
        style={{
          flex: 1,
          backgroundColor: C.bg,
          alignItems: "center",
          justifyContent: "center",
          padding: spacing.lg,
        }}
      >
        <Text style={{ color: C.textMuted, textAlign: "center" }}>
          Could not load profile.
        </Text>
      </View>
    );
  }

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
          Profile Card
        </Text>
        {isSavingColors && <ActivityIndicator size="small" color={C.primary} />}
      </View>

      <ScrollView
        showsVerticalScrollIndicator={false}
        contentContainerStyle={{
          padding: spacing.md,
          gap: spacing.lg,
          paddingBottom: insets.bottom + spacing.lg,
        }}
      >
        {/* Card */}
        <ProfileCard
          profile={profile}
          stats={stats}
          accentColors={selectedColors}
        />

        {/* Color customization */}
        <View style={{ gap: spacing.sm }}>
          <Text
            style={{
              fontSize: fontSize.xs,
              color: C.textMuted,
              textTransform: "uppercase",
              letterSpacing: 1,
              fontWeight: "600",
            }}
          >
            Card Accent Color
          </Text>
          <View style={{ flexDirection: "row", gap: spacing.sm }}>
            {ACCENT_PRESETS.map((preset) => {
              const isSelected = preset.accent === selectedColors.accent;
              return (
                <Pressable
                  key={preset.accent}
                  onPress={() => {
                    void handleSelectColor(preset);
                  }}
                  style={{
                    width: 36,
                    height: 36,
                    borderRadius: 18,
                    backgroundColor: preset.accent,
                    borderWidth: isSelected ? 3 : 2,
                    borderColor: isSelected ? C.text : "rgba(255,255,255,0.15)",
                    shadowColor: preset.accent,
                    shadowOffset: { width: 0, height: 2 },
                    shadowOpacity: isSelected ? 0.6 : 0,
                    shadowRadius: 6,
                    elevation: isSelected ? 4 : 0,
                  }}
                />
              );
            })}
          </View>
        </View>

        {/* Actions */}
        <View style={{ gap: spacing.sm }}>
          <Pressable
            onPress={() => {
              void handleShareProfile();
            }}
            style={{
              backgroundColor: C.primary,
              borderRadius: 14,
              paddingVertical: spacing.md,
              flexDirection: "row",
              alignItems: "center",
              justifyContent: "center",
              gap: spacing.sm,
            }}
          >
            <AppIcon icon={Share01Icon} size={18} color="#000" />
            <Text
              style={{
                color: "#000",
                fontWeight: "600",
                fontSize: fontSize.base,
              }}
            >
              Share Profile
            </Text>
          </Pressable>

          <Pressable
            onPress={() => {
              void handleCopyLink();
            }}
            style={{
              backgroundColor: C.surface,
              borderRadius: 14,
              paddingVertical: spacing.md,
              flexDirection: "row",
              alignItems: "center",
              justifyContent: "center",
              gap: spacing.sm,
              borderWidth: 1,
              borderColor: C.divider,
            }}
          >
            <AppIcon icon={Copy01Icon} size={18} color={C.textMuted} />
            <Text
              style={{
                color: C.textMuted,
                fontWeight: "500",
                fontSize: fontSize.base,
              }}
            >
              Copy Profile Link
            </Text>
          </Pressable>
        </View>
      </ScrollView>
    </View>
  );
}
