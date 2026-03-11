import * as ImagePicker from "expo-image-picker";
import { Avatar, Button, Card, Spinner, TextField } from "heroui-native";
import { useCallback, useEffect, useState } from "react";
import { Alert, ScrollView, View } from "react-native";
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
        <Spinner />
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
      <Card variant="secondary" className="rounded-3xl bg-surface">
        <Card.Body className="items-center gap-4 px-5 py-6">
          <Avatar alt={profile?.name ?? "User"} size="lg" color="accent">
            {profile?.picture ? (
              <Avatar.Image source={{ uri: profile.picture }} />
            ) : (
              <Avatar.Fallback>{getInitials(profile?.name)}</Avatar.Fallback>
            )}
          </Avatar>
          <Button
            variant="tertiary"
            onPress={() => {
              void handlePickAvatar();
            }}
            isDisabled={isSaving}
            className="bg-primary/10"
          >
            <Button.Label className="text-primary">
              {isSaving ? "Updating…" : "Change Photo"}
            </Button.Label>
          </Button>
          <Text style={{ fontSize: fontSize.xs, color: C.textMuted }}>
            Tap to change photo
          </Text>
        </Card.Body>
      </Card>

      <Card variant="secondary" className="rounded-3xl bg-surface">
        <Card.Body className="gap-4 px-5 py-5">
          <TextField>
            <TextField.Label>Display Name</TextField.Label>
            <TextField.Input
              value={displayName}
              onChangeText={setDisplayName}
              onBlur={() => {
                void handleSaveDisplayName();
              }}
              placeholder="Your name"
              autoCapitalize="words"
              returnKeyType="done"
            />
          </TextField>

          <TextField>
            <TextField.Label>Bio</TextField.Label>
            <TextField.Input
              value={bio}
              onChangeText={setBio}
              onBlur={() => {
                void handleSaveBio();
              }}
              multiline
              numberOfLines={4}
              placeholder="Tell GAIA about yourself…"
              style={{ minHeight: 100 }}
            />
          </TextField>
        </Card.Body>
      </Card>

      <Button
        onPress={() => {
          void handleSaveAll();
        }}
        isDisabled={isSaving}
        className="bg-primary"
      >
        {isSaving ? <Spinner /> : <Button.Label>Save Profile</Button.Label>}
      </Button>
    </ScrollView>
  );
}
