import type { BottomSheetModal } from "@gorhom/bottom-sheet";
import { useRouter } from "expo-router";
import { Avatar } from "heroui-native";
import { useCallback, useRef } from "react";
import { ActivityIndicator, Pressable, View } from "react-native";
import { ArrowDown01Icon, HugeiconsIcon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useAuth } from "@/features/auth";
import { SettingsBottomSheet } from "./settings-bottom-sheet";

export function SidebarFooter() {
  const { user, isLoading, signOut } = useAuth();
  const bottomSheetRef = useRef<BottomSheetModal>(null);
  const router = useRouter();

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
      <View className="border-t border-border py-2">
        <View className="py-6 items-center justify-center">
          <ActivityIndicator size="small" color="#00bbff" />
        </View>
      </View>
    );
  }

  return (
    <>
      <View className="border-t border-border py-3">
        <Pressable
          className="flex-row items-center px-4 py-2 gap-3"
          onPress={handleOpenSettings}
        >
          <Avatar alt={user?.name || "User"} size="sm" color="accent">
            {profilePicture ? (
              <Avatar.Image source={{ uri: profilePicture }} />
            ) : (
              <Avatar.Fallback>{getInitials(user?.name)}</Avatar.Fallback>
            )}
          </Avatar>
          <View className="flex-1">
            <Text className="text-sm font-semibold" numberOfLines={1}>
              {user?.name || "User"}
            </Text>
            <Text className="text-[9px] text-muted uppercase font-bold tracking-[0.15em]">
              GAIA Free
            </Text>
          </View>
          <HugeiconsIcon icon={ArrowDown01Icon} size={16} color="#8e8e93" />
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
