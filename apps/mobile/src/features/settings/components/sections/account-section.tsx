import { useRouter } from "expo-router";
import { Avatar, Button, Card, Spinner, TextField } from "heroui-native";
import { useCallback, useEffect, useState } from "react";
import { Alert, ScrollView } from "react-native";
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
      <Card variant="secondary" className="rounded-3xl bg-surface">
        <Card.Body className="items-center gap-3 px-5 py-6">
          <Avatar alt={user?.name ?? "User"} size="lg" color="accent">
            {user?.picture ? (
              <Avatar.Image source={{ uri: user.picture }} />
            ) : (
              <Avatar.Fallback>{getInitials(user?.name)}</Avatar.Fallback>
            )}
          </Avatar>
          <Text style={{ fontSize: fontSize.sm, color: "#8e8e93" }}>
            {user?.email ?? ""}
          </Text>
        </Card.Body>
      </Card>

      <Card variant="secondary" className="rounded-3xl bg-surface">
        <Card.Body className="gap-4 px-5 py-5">
          <TextField>
            <TextField.Label>Display Name</TextField.Label>
            <TextField.Input
              value={name}
              onChangeText={setName}
              placeholder="Your name"
              autoCapitalize="words"
              returnKeyType="done"
              onSubmitEditing={() => {
                void handleSaveName();
              }}
            />
          </TextField>

          <TextField>
            <TextField.Label>Email</TextField.Label>
            <TextField.Input value={user?.email ?? "—"} editable={false} />
            <TextField.Description>
              Your WorkOS email stays read-only here.
            </TextField.Description>
          </TextField>

          {isDirty ? (
            <Button
              onPress={() => {
                void handleSaveName();
              }}
              isDisabled={isSaving}
              className="bg-primary"
            >
              {isSaving ? <Spinner /> : <Button.Label>Save Name</Button.Label>}
            </Button>
          ) : null}
        </Card.Body>
      </Card>

      <Button
        onPress={() => {
          void handleSignOut();
        }}
        isDisabled={isSigningOut}
        variant="tertiary"
        className="bg-danger/10"
      >
        <AppIcon icon={Logout01Icon} size={18} color="#ef4444" />
        {isSigningOut ? (
          <Spinner />
        ) : (
          <Button.Label className="text-danger">Sign Out</Button.Label>
        )}
      </Button>
    </ScrollView>
  );
}
