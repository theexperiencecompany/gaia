import type { BottomSheetModal } from "@gorhom/bottom-sheet";
import { useRouter } from "expo-router";
import { Avatar } from "heroui-native";
import { useCallback, useRef } from "react";
import { ActivityIndicator, Pressable, View } from "react-native";
import { ArrowDown01Icon, HugeiconsIcon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useAuth } from "@/features/auth";
import { useResponsive } from "@/lib/responsive";
import { SettingsBottomSheet } from "./settings-bottom-sheet";

export function SidebarFooter() {
  const { user, isLoading, signOut } = useAuth();
  const bottomSheetRef = useRef<BottomSheetModal>(null);
  const router = useRouter();
  const { spacing, fontSize, iconSize } = useResponsive();

  const handleSignOut = useCallback(async () => {
    bottomSheetRef.current?.dismiss();
    await signOut();
    router.replace("/login");
  }, [signOut, router]);

  const getInitials = (name?: string) => {
    if (!name) return "U";
    const parts = name.trim().split(" ");
    if (parts.length >= 2) {
      return `${parts[0][0]}${parts[parts.length - 1][0]}`.toUpperCase();
    }
    return name[0].toUpperCase();
  };

  const handleOpenSettings = () => {
    bottomSheetRef.current?.present();
  };

  const profilePicture = user?.picture;

  if (isLoading) {
    return (
      <View
        style={{
          borderTopWidth: 1,
          borderTopColor: "rgba(255,255,255,0.1)",
          paddingVertical: spacing.sm,
        }}
      >
        <View
          style={{
            paddingVertical: spacing.lg,
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <ActivityIndicator size="small" color="#00bbff" />
        </View>
      </View>
    );
  }

  return (
    <>
      <View
        style={{
          borderTopWidth: 1,
          borderTopColor: "rgba(255,255,255,0.1)",
          paddingVertical: spacing.md,
        }}
      >
        <Pressable
          style={{
            flexDirection: "row",
            alignItems: "center",
            paddingHorizontal: spacing.md,
            paddingVertical: spacing.sm,
            gap: spacing.md,
          }}
          onPress={handleOpenSettings}
        >
          <Avatar alt={user?.name || "User"} size="sm" color="accent">
            {profilePicture ? (
              <Avatar.Image source={{ uri: profilePicture }} />
            ) : (
              <Avatar.Fallback>{getInitials(user?.name)}</Avatar.Fallback>
            )}
          </Avatar>
          <View style={{ flex: 1 }}>
            <Text
              style={{ fontSize: fontSize.sm, fontWeight: "600" }}
              numberOfLines={1}
            >
              {user?.name || "User"}
            </Text>
            <Text
              style={{
                fontSize: fontSize.xs - 1,
                color: "#8e8e93",
                textTransform: "uppercase",
                fontWeight: "bold",
                letterSpacing: 1.5,
              }}
            >
              GAIA Free
            </Text>
          </View>
          <HugeiconsIcon
            icon={ArrowDown01Icon}
            size={iconSize.sm}
            color="#8e8e93"
          />
        </Pressable>
      </View>

      <SettingsBottomSheet
        ref={bottomSheetRef}
        user={user}
        onSignOut={handleSignOut}
      />
    </>
  );
}
