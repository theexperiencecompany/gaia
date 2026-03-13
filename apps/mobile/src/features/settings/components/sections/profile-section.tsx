import { Image } from "expo-image";
import * as ImagePicker from "expo-image-picker";
import { useRouter } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  ScrollView,
  TextInput,
  View,
} from "react-native";
import {
  AppIcon,
  ArrowRight01Icon,
  UserCircle02Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import type {
  UserProfile,
  UserStats,
} from "@/features/settings/api/settings-api";
import { settingsApi } from "@/features/settings/api/settings-api";
import { useResponsive } from "@/lib/responsive";

const C = {
  bg: "#1c1c1e",
  surface: "#1a1c21",
  primary: "#00bbff",
  primaryBg: "rgba(0,187,255,0.15)",
  text: "#ffffff",
  textMuted: "#8e8e93",
  textSubtle: "#5a5a5e",
  divider: "rgba(255,255,255,0.06)",
};

function getInitials(name?: string): string {
  if (!name) return "U";
  const parts = name.trim().split(" ");
  if (parts.length >= 2) {
    return `${parts[0][0]}${parts[parts.length - 1][0]}`.toUpperCase();
  }
  return name[0].toUpperCase();
}

export function ProfileSection() {
  const router = useRouter();
  const { spacing, fontSize } = useResponsive();
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [stats, setStats] = useState<UserStats | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);

  const [displayName, setDisplayName] = useState("");
  const [bio, setBio] = useState("");

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    Promise.all([settingsApi.getProfile(), settingsApi.getUserStats()])
      .then(([profileData, statsData]) => {
        if (cancelled) return;
        setProfile(profileData);
        setStats(statsData);
        setDisplayName(profileData.name ?? "");
        setBio(profileData.onboarding?.preferences?.custom_instructions ?? "");
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

  const handlePickAvatar = useCallback(async () => {
    const { status } = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (status !== "granted") {
      Alert.alert(
        "Permission required",
        "Allow access to your photo library to change your avatar.",
      );
      return;
    }

    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ["images"],
      allowsEditing: true,
      aspect: [1, 1],
      quality: 0.8,
    });

    if (result.canceled || !result.assets[0]) return;

    const asset = result.assets[0];
    setIsSaving(true);
    try {
      const form = new FormData();
      form.append("picture", {
        uri: asset.uri,
        name: asset.fileName ?? "avatar.jpg",
        type: asset.mimeType ?? "image/jpeg",
      } as unknown as Blob);
      const updated = await settingsApi.updateProfile(form);
      setProfile(updated);
    } catch {
      Alert.alert("Error", "Failed to update avatar. Please try again.");
    } finally {
      setIsSaving(false);
    }
  }, []);

  const handleSaveDisplayName = useCallback(async () => {
    const trimmed = displayName.trim();
    if (!trimmed || trimmed === profile?.name) return;
    setIsSaving(true);
    try {
      const form = new FormData();
      form.append("name", trimmed);
      const updated = await settingsApi.updateProfile(form);
      setProfile(updated);
    } catch {
      Alert.alert("Error", "Failed to update name. Please try again.");
      setDisplayName(profile?.name ?? "");
    } finally {
      setIsSaving(false);
    }
  }, [displayName, profile?.name]);

  const _handleSaveBio = useCallback(async () => {
    const trimmed = bio.trim();
    const original =
      profile?.onboarding?.preferences?.custom_instructions ?? "";
    if (trimmed === original) return;
    setIsSaving(true);
    try {
      await settingsApi.updatePreferences({
        custom_instructions: trimmed || null,
      });
    } catch {
      Alert.alert("Error", "Failed to update bio. Please try again.");
      setBio(original);
    } finally {
      setIsSaving(false);
    }
  }, [bio, profile?.onboarding?.preferences?.custom_instructions]);

  const handleSaveAll = useCallback(async () => {
    setIsSaving(true);
    try {
      const nameForm = new FormData();
      nameForm.append("name", displayName.trim() || (profile?.name ?? ""));
      await settingsApi.updateProfile(nameForm);
      await settingsApi.updatePreferences({
        custom_instructions: bio.trim() || null,
      });
      Alert.alert("Saved", "Profile updated.");
    } catch {
      Alert.alert("Error", "Failed to save profile. Please try again.");
    } finally {
      setIsSaving(false);
    }
  }, [displayName, bio, profile?.name]);

  const avatarUri = profile?.picture ?? null;

  if (isLoading) {
    return (
      <View style={{ flex: 1, alignItems: "center", justifyContent: "center" }}>
        <ActivityIndicator color="#00bbff" />
      </View>
    );
  }

  return (
    <ScrollView
      showsVerticalScrollIndicator={false}
      keyboardShouldPersistTaps="handled"
      contentContainerStyle={{
        padding: spacing.md,
        gap: spacing.lg,
        paddingBottom: 40,
      }}
    >
      {/* Avatar + name hero */}
      <View style={{ alignItems: "center", paddingVertical: spacing.md }}>
        <Pressable
          onPress={() => {
            void handlePickAvatar();
          }}
          style={{ position: "relative" }}
        >
          <View
            style={{
              width: 80,
              height: 80,
              borderRadius: 40,
              backgroundColor: C.primaryBg,
              alignItems: "center",
              justifyContent: "center",
              overflow: "hidden",
            }}
          >
            {avatarUri ? (
              <Image
                source={{ uri: avatarUri }}
                style={{ width: 80, height: 80, borderRadius: 40 }}
                contentFit="cover"
              />
            ) : (
              <Text
                style={{
                  fontSize: fontSize["2xl"],
                  fontWeight: "700",
                  color: C.primary,
                }}
              >
                {getInitials(profile?.name)}
              </Text>
            )}
          </View>
        </Pressable>

        <Text
          style={{
            marginTop: spacing.sm,
            fontSize: fontSize.lg,
            fontWeight: "700",
            color: C.text,
          }}
        >
          {profile?.name ?? ""}
        </Text>
        <Text
          style={{
            marginTop: 2,
            fontSize: fontSize.sm,
            color: C.textMuted,
          }}
        >
          {profile?.email ?? ""}
        </Text>
        <Text
          style={{
            marginTop: spacing.xs,
            fontSize: fontSize.xs,
            color: C.textSubtle,
          }}
        >
          Tap photo to change
        </Text>
      </View>

      {/* Stats row */}
      {stats ? (
        <View
          style={{
            backgroundColor: C.surface,
            borderRadius: 16,
            padding: spacing.md,
            flexDirection: "row",
            justifyContent: "space-around",
            borderWidth: 1,
            borderColor: C.divider,
          }}
        >
          <View style={{ alignItems: "center" }}>
            <Text
              style={{
                fontSize: fontSize["2xl"],
                fontWeight: "700",
                color: C.primary,
              }}
            >
              {stats.conversation_count}
            </Text>
            <Text style={{ fontSize: fontSize.xs, color: C.textMuted }}>
              Conversations
            </Text>
          </View>
          <View style={{ width: 1, backgroundColor: C.divider }} />
          <View style={{ alignItems: "center" }}>
            <Text
              style={{
                fontSize: fontSize["2xl"],
                fontWeight: "700",
                color: C.primary,
              }}
            >
              {stats.workflow_count}
            </Text>
            <Text style={{ fontSize: fontSize.xs, color: C.textMuted }}>
              Workflows
            </Text>
          </View>
          <View style={{ width: 1, backgroundColor: C.divider }} />
          <View style={{ alignItems: "center" }}>
            <Text
              style={{
                fontSize: fontSize["2xl"],
                fontWeight: "700",
                color: C.primary,
              }}
            >
              {stats.integration_count}
            </Text>
            <Text style={{ fontSize: fontSize.xs, color: C.textMuted }}>
              Integrations
            </Text>
          </View>
        </View>
      ) : null}

      {/* View profile card CTA */}
      <Pressable
        onPress={() => router.push("/profile-card")}
        style={{
          backgroundColor: C.surface,
          borderRadius: 14,
          paddingHorizontal: spacing.md,
          paddingVertical: spacing.md,
          flexDirection: "row",
          alignItems: "center",
          gap: spacing.sm,
          borderWidth: 1,
          borderColor: "rgba(0,187,255,0.2)",
        }}
      >
        <View
          style={{
            width: 34,
            height: 34,
            borderRadius: 9,
            backgroundColor: C.primaryBg,
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <AppIcon icon={UserCircle02Icon} size={18} color={C.primary} />
        </View>
        <View style={{ flex: 1 }}>
          <Text
            style={{
              fontSize: fontSize.sm + 1,
              color: C.text,
              fontWeight: "500",
            }}
          >
            View Profile Card
          </Text>
          <Text style={{ fontSize: fontSize.xs, color: C.textMuted }}>
            Customize and share your GAIA card
          </Text>
        </View>
        <AppIcon icon={ArrowRight01Icon} size={16} color={C.textMuted} />
      </Pressable>

      {/* Display name field */}
      <View style={{ gap: spacing.xs }}>
        <Text
          style={{
            fontSize: fontSize.xs,
            color: C.textMuted,
            textTransform: "uppercase",
            letterSpacing: 1,
          }}
        >
          Display Name
        </Text>
        <TextInput
          value={displayName}
          onChangeText={setDisplayName}
          onBlur={() => {
            void handleSaveDisplayName();
          }}
          style={{
            backgroundColor: C.bg,
            borderRadius: 12,
            paddingHorizontal: spacing.md,
            paddingVertical: spacing.md,
            fontSize: fontSize.base,
            color: C.text,
          }}
          placeholderTextColor={C.textSubtle}
          placeholder="Your name"
          autoCapitalize="words"
          returnKeyType="done"
        />
      </View>

      {/* Save button */}
      <Pressable
        onPress={() => {
          void handleSaveAll();
        }}
        disabled={isSaving}
        style={{
          backgroundColor: C.primary,
          borderRadius: 14,
          paddingVertical: spacing.md,
          alignItems: "center",
          justifyContent: "center",
          flexDirection: "row",
          gap: spacing.xs,
          opacity: isSaving ? 0.7 : 1,
        }}
      >
        {isSaving ? <ActivityIndicator size="small" color="#000" /> : null}
        <Text
          style={{ color: "#000", fontWeight: "700", fontSize: fontSize.sm }}
        >
          {isSaving ? "Saving..." : "Save Profile"}
        </Text>
      </Pressable>
    </ScrollView>
  );
}
