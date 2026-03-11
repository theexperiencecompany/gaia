import { useRouter } from "expo-router";
import { Avatar } from "heroui-native";
import { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  ScrollView,
  TextInput,
  View,
} from "react-native";
import { AppIcon, Logout01Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useAuth } from "@/features/auth";
import { apiService } from "@/lib/api";
import { useResponsive } from "@/lib/responsive";

interface UpdateNameResponse {
  success: boolean;
}

function getInitials(name?: string): string {
  if (!name) return "U";
  const parts = name.trim().split(" ");
  if (parts.length >= 2) {
    return `${parts[0][0]}${parts[parts.length - 1][0]}`.toUpperCase();
  }
  return name[0].toUpperCase();
}

export function AccountSection() {
  const { user, signOut, refreshAuth } = useAuth();
  const router = useRouter();
  const { spacing, fontSize } = useResponsive();

  const [name, setName] = useState(user?.name ?? "");
  const [isSaving, setIsSaving] = useState(false);
  const [isSigningOut, setIsSigningOut] = useState(false);
  const isDirty = name.trim() !== (user?.name ?? "").trim();

  useEffect(() => {
    if (user?.name) setName(user.name);
  }, [user?.name]);

  const handleSaveName = useCallback(async () => {
    const trimmed = name.trim();
    if (!trimmed || !isDirty) return;
    setIsSaving(true);
    try {
      const form = new FormData();
      form.append("name", trimmed);
      await apiService.patch<UpdateNameResponse>("/user/name", form);
      await refreshAuth();
    } catch {
      Alert.alert("Error", "Failed to update name. Please try again.");
    } finally {
      setIsSaving(false);
    }
  }, [name, isDirty, refreshAuth]);

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
    <ScrollView
      showsVerticalScrollIndicator={false}
      contentContainerStyle={{ padding: spacing.md, gap: spacing.lg }}
    >
      {/* Avatar */}
      <View style={{ alignItems: "center", paddingVertical: spacing.md }}>
        <Avatar alt={user?.name ?? "User"} size="lg" color="accent">
          {user?.picture ? (
            <Avatar.Image source={{ uri: user.picture }} />
          ) : (
            <Avatar.Fallback>{getInitials(user?.name)}</Avatar.Fallback>
          )}
        </Avatar>
        <Text
          style={{
            marginTop: spacing.sm,
            fontSize: fontSize.sm,
            color: "#8e8e93",
          }}
        >
          {user?.email ?? ""}
        </Text>
      </View>

      {/* Name field */}
      <View style={{ gap: spacing.xs }}>
        <Text
          style={{
            fontSize: fontSize.xs,
            color: "#8e8e93",
            textTransform: "uppercase",
            letterSpacing: 1,
          }}
        >
          Display Name
        </Text>
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            backgroundColor: "#1c1c1e",
            borderRadius: 12,
            paddingHorizontal: spacing.md,
            borderWidth: 1,
            borderColor: isDirty ? "rgba(22,193,255,0.4)" : "transparent",
          }}
        >
          <TextInput
            value={name}
            onChangeText={setName}
            style={{
              flex: 1,
              fontSize: fontSize.base,
              color: "#ffffff",
              paddingVertical: spacing.md,
            }}
            placeholderTextColor="#6b6b6b"
            placeholder="Your name"
            autoCapitalize="words"
            returnKeyType="done"
            onSubmitEditing={() => {
              void handleSaveName();
            }}
          />
          {isDirty && (
            <Pressable
              onPress={() => {
                void handleSaveName();
              }}
              disabled={isSaving}
              style={{
                backgroundColor: "#16c1ff",
                borderRadius: 8,
                paddingHorizontal: spacing.md,
                paddingVertical: spacing.xs,
                opacity: isSaving ? 0.6 : 1,
              }}
            >
              {isSaving ? (
                <ActivityIndicator size="small" color="#000" />
              ) : (
                <Text
                  style={{
                    color: "#000",
                    fontSize: fontSize.xs,
                    fontWeight: "600",
                  }}
                >
                  Save
                </Text>
              )}
            </Pressable>
          )}
        </View>
      </View>

      {/* Email (read-only) */}
      <View style={{ gap: spacing.xs }}>
        <Text
          style={{
            fontSize: fontSize.xs,
            color: "#8e8e93",
            textTransform: "uppercase",
            letterSpacing: 1,
          }}
        >
          Email
        </Text>
        <View
          style={{
            backgroundColor: "#1c1c1e",
            borderRadius: 12,
            paddingHorizontal: spacing.md,
            paddingVertical: spacing.md,
          }}
        >
          <Text style={{ fontSize: fontSize.base, color: "#8e8e93" }}>
            {user?.email ?? "—"}
          </Text>
        </View>
      </View>

      {/* Sign Out */}
      <Pressable
        onPress={() => {
          void handleSignOut();
        }}
        disabled={isSigningOut}
        style={{
          flexDirection: "row",
          alignItems: "center",
          gap: spacing.sm,
          backgroundColor: "rgba(239,68,68,0.08)",
          borderRadius: 12,
          paddingHorizontal: spacing.md,
          paddingVertical: spacing.md,
          opacity: isSigningOut ? 0.6 : 1,
          marginTop: spacing.md,
        }}
      >
        <HugeiconsIcon icon={Logout01Icon} size={20} color="#ef4444" />
        <Text style={{ color: "#ef4444", fontSize: fontSize.base }}>
          {isSigningOut ? "Signing out…" : "Sign Out"}
        </Text>
      </Pressable>
    </ScrollView>
  );
}
