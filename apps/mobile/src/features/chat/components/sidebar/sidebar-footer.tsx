import { useRef } from "react";
import { ActivityIndicator, View, Pressable } from "react-native";
import { ArrowDown01Icon, HugeiconsIcon } from "@/components/icons";
import { Avatar, Popover, type PopoverTriggerRef } from "heroui-native";
import { useAuth } from "@/features/auth";
import { Text } from "@/components/ui/text";
import { SettingsSheetContent } from "./settings-sheet";

export function SidebarFooter() {
  const { user, isLoading, signOut } = useAuth();
  const popoverRef = useRef<PopoverTriggerRef>(null);

  const getInitials = (name?: string) => {
    if (!name) return "U";
    const parts = name.trim().split(" ");
    if (parts.length >= 2) {
      return `${parts[0][0]}${parts[parts.length - 1][0]}`.toUpperCase();
    }
    return name[0].toUpperCase();
  };

  const handleOpenSettings = () => {
    popoverRef.current?.open();
  };

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
    <View className="border-t border-border py-3">
      <Popover>
        <Popover.Trigger ref={popoverRef} asChild={false}>
          <Pressable
            className="flex-row items-center px-4 py-2 gap-3"
            onPress={handleOpenSettings}
          >
            <Avatar alt="user" size="sm" color="accent">
              {user?.picture ? (
                <Avatar.Image source={{ uri: user.picture }} />
              ) : null}
              <Avatar.Fallback>{getInitials(user?.name)}</Avatar.Fallback>
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
        </Popover.Trigger>
        <Popover.Portal>
          <Popover.Overlay />
          <Popover.Content
            presentation="bottom-sheet"
            snapPoints={["90%"]}
            index={0}
          >
            <SettingsSheetContent user={user} onSignOut={signOut} />
          </Popover.Content>
        </Popover.Portal>
      </Popover>
    </View>
  );
}
