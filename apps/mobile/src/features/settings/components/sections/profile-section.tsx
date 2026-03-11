import * as ImagePicker from "expo-image-picker";
import { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Image,
  Pressable,
  ScrollView,
  TextInput,
  View,
} from "react-native";
import { Text } from "@/components/ui/text";
import type { UserProfile } from "@/features/settings/api/settings-api";
import { settingsApi } from "@/features/settings/api/settings-api";
import { useResponsive } from "@/lib/responsive";

const C = {
  bg: "#1c1c1e",
  primary: "#00bbff",
  primaryBg: "rgba(0,187,255,0.15)",
  text: "#ffffff",
  textMuted: "#8e8e93",
  textSubtle: "#5a5a5e",
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
  const { spacing, fontSize } = useResponsive();
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);

  const [displayName, setDisplayName] = useState("");
  const [bio, setBio] = useState("");

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    settingsApi
      .getProfile()
      .then((data) => {
        if (cancelled) return;
        setProfile(data);
        setDisplayName(data.name ?? "");
        setBio(data.onboarding?.preferences?.custom_instructions ?? "");
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

  const handleSaveBio = useCallback(async () => {
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

  if (isLoading) {
    return (
      <View style={{ flex: 1, alignItems: "center", justifyContent: "center" }}>
        <ActivityIndicator color={C.primary} />
      </View>
    );
  }

  const avatarUri = profile?.picture;
  const initials = getInitials(profile?.name);

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
      {/* Avatar */}
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
                resizeMode="cover"
              />
            ) : (
              <Text
                style={{
                  fontSize: 28,
                  fontWeight: "700",
                  color: C.primary,
                }}
              >
                {initials}
              </Text>
            )}
          </View>

          {/* Camera badge */}
          <View
            style={{
              position: "absolute",
              bottom: 0,
              right: 0,
              width: 24,
              height: 24,
              borderRadius: 12,
              backgroundColor: C.primary,
              alignItems: "center",
              justifyContent: "center",
              borderWidth: 2,
              borderColor: "#0b0c0f",
            }}
          >
            <Text style={{ fontSize: 11, color: "#000" }}>+</Text>
          </View>
        </Pressable>

        <Text
          style={{
            marginTop: spacing.sm,
            fontSize: fontSize.xs,
            color: C.textMuted,
          }}
        >
          Tap to change photo
        </Text>
      </View>

      {/* Display name */}
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

      {/* Bio */}
      <View style={{ gap: spacing.xs }}>
        <Text
          style={{
            fontSize: fontSize.xs,
            color: C.textMuted,
            textTransform: "uppercase",
            letterSpacing: 1,
          }}
        >
          Bio
        </Text>
        <TextInput
          value={bio}
          onChangeText={setBio}
          onBlur={() => {
            void handleSaveBio();
          }}
          multiline
          numberOfLines={4}
          style={{
            backgroundColor: C.bg,
            borderRadius: 12,
            paddingHorizontal: spacing.md,
            paddingVertical: spacing.md,
            fontSize: fontSize.sm,
            color: C.text,
            minHeight: 100,
            textAlignVertical: "top",
          }}
          placeholderTextColor={C.textSubtle}
          placeholder="Tell GAIA about yourself…"
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
          borderRadius: 12,
          paddingVertical: spacing.md,
          alignItems: "center",
          opacity: isSaving ? 0.6 : 1,
          marginTop: spacing.sm,
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
            Save Profile
          </Text>
        )}
      </Pressable>
    </ScrollView>
  );
}
