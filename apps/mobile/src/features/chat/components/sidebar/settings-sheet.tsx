import { Avatar, Button } from "heroui-native";
import { Linking, Pressable, View } from "react-native";
import {
  HugeiconsIcon,
  Logout01Icon,
  Moon02Icon,
  Settings01Icon,
  UserIcon,
  CustomerSupportIcon,
  InformationSquareIcon,
  FavouriteIcon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import type { UserInfo } from "@/features/auth";

interface SettingsSheetProps {
  user: UserInfo | null;
  onSignOut: () => void;
}

interface SettingsItemProps {
  icon: unknown;
  label: string;
  onPress: () => void;
  iconColor?: string;
}

function SettingsItem({
  icon,
  label,
  onPress,
  iconColor = "#a1a1aa",
}: SettingsItemProps) {
  return (
    <Pressable
      onPress={onPress}
      className="flex-row items-center px-4 py-3 active:bg-white/5"
    >
      <View
        style={{ backgroundColor: "#141414" }}
        className="w-8 h-8 rounded-lg items-center justify-center mr-3"
      >
        <HugeiconsIcon icon={icon} size={16} color={iconColor} />
      </View>
      <Text className="flex-1 text-sm">{label}</Text>
    </Pressable>
  );
}

export function SettingsSheetContent({ user, onSignOut }: SettingsSheetProps) {
  const getInitials = (name?: string) => {
    if (!name) return "U";
    const parts = name.trim().split(" ");
    if (parts.length >= 2) {
      return `${parts[0][0]}${parts[parts.length - 1][0]}`.toUpperCase();
    }
    return name[0].toUpperCase();
  };

  const openLink = (url: string) => {
    Linking.openURL(url);
  };

  return (
    <View className="pb-4">
      {/* User Profile Section */}
      <Pressable className="flex-row items-center px-4 py-3 active:bg-white/5">
        <Avatar alt="user" size="md" color="accent">
          {user?.picture ? (
            <Avatar.Image source={{ uri: user.picture }} />
          ) : null}
          <Avatar.Fallback>{getInitials(user?.name)}</Avatar.Fallback>
        </Avatar>
        <View className="flex-1 ml-3">
          <Text className="font-semibold" numberOfLines={1}>
            {user?.name || "User"}
          </Text>
          <Text className="text-xs text-muted" numberOfLines={1}>
            {user?.email || ""}
          </Text>
        </View>
      </Pressable>

      {/* Upgrade to Pro */}
      <Pressable
        style={{ backgroundColor: "#141414" }}
        className="mx-4 my-2 py-3 px-4 rounded-xl flex-row items-center"
        onPress={() => openLink("https://gaia.com/pricing")}
      >
        <HugeiconsIcon icon={FavouriteIcon} size={18} color="#00bbff" />
        <Text className="ml-3 text-sm font-medium">Upgrade to Pro</Text>
      </Pressable>

      {/* Divider */}
      <View className="h-px bg-white/5 mx-4 my-2" />

      {/* Settings Section */}
      <Text className="text-xs text-muted px-4 py-2 uppercase tracking-wider">
        Settings
      </Text>
      <SettingsItem icon={UserIcon} label="Profile" onPress={() => {}} />
      <SettingsItem
        icon={Settings01Icon}
        label="Preferences"
        onPress={() => {}}
      />
      <SettingsItem icon={Moon02Icon} label="Appearance" onPress={() => {}} />

      {/* Divider */}
      <View className="h-px bg-white/5 mx-4 my-2" />

      {/* Support Section */}
      <Text className="text-xs text-muted px-4 py-2 uppercase tracking-wider">
        Support
      </Text>
      <SettingsItem
        icon={CustomerSupportIcon}
        label="Help & Support"
        onPress={() => openLink("https://gaia.com/support")}
      />
      <SettingsItem
        icon={InformationSquareIcon}
        label="About"
        onPress={() => {}}
      />

      {/* Divider */}
      <View className="h-px bg-white/5 mx-4 my-2" />

      {/* Logout */}
      <View className="px-4 pt-2">
        <Button
          onPress={onSignOut}
          variant="ghost"
          style={{ backgroundColor: "#141414" }}
          className="border-0"
        >
          <HugeiconsIcon icon={Logout01Icon} size={16} color="#ef4444" />
          <Button.Label>Sign out</Button.Label>
        </Button>
      </View>
    </View>
  );
}
