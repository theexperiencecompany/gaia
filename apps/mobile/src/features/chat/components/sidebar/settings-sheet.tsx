import { Avatar, Button, Divider, Popover } from "heroui-native";
import { ScrollView, View } from "react-native";
import {
  ArrowRight01Icon,
  HugeiconsIcon,
  Logout01Icon,
  Moon02Icon,
  Notification01Icon,
  Settings01Icon,
  ShieldKeyIcon,
  UserIcon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";

interface SettingsSheetProps {
  user?: {
    name?: string;
    email?: string;
    picture?: string;
  } | null;
  onSignOut: () => void;
}

interface SettingsItemProps {
  icon: unknown;
  label: string;
  onPress: () => void;
}

function SettingsItem({ icon, label, onPress }: SettingsItemProps) {
  return (
    <Button
      variant="ghost"
      onPress={onPress}
      className="justify-start px-4 py-3"
    >
      <HugeiconsIcon icon={icon} size={18} color="#8e8e93" />
      <Button.Label className="flex-1 ml-3 text-sm text-foreground">
        {label}
      </Button.Label>
      <HugeiconsIcon icon={ArrowRight01Icon} size={14} color="#8e8e93" />
    </Button>
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

  return (
    <ScrollView className="flex-1">
      <View className="flex-row items-center justify-between px-4 pb-4">
        <Text className="text-lg font-semibold">Settings</Text>
        <Popover.Close />
      </View>

      <View className="flex-row items-center px-4 py-3 gap-3">
        <Avatar alt="user" size="md" color="accent">
          {user?.picture ? (
            <Avatar.Image source={{ uri: user.picture }} />
          ) : null}
          <Avatar.Fallback>{getInitials(user?.name)}</Avatar.Fallback>
        </Avatar>
        <View className="flex-1">
          <Text className="font-semibold" numberOfLines={1}>
            {user?.name || "User"}
          </Text>
          <Text className="text-xs text-muted" numberOfLines={1}>
            {user?.email || ""}
          </Text>
        </View>
        <HugeiconsIcon icon={ArrowRight01Icon} size={16} color="#8e8e93" />
      </View>

      <Divider className="my-2" />

      <Text className="text-xs text-muted px-4 py-2 uppercase tracking-wider">
        General
      </Text>

      <View>
        <SettingsItem icon={UserIcon} label="Profile" onPress={() => {}} />
        <SettingsItem icon={Moon02Icon} label="Appearance" onPress={() => {}} />
        <SettingsItem
          icon={Notification01Icon}
          label="Notifications"
          onPress={() => {}}
        />
        <SettingsItem
          icon={ShieldKeyIcon}
          label="Privacy & Security"
          onPress={() => {}}
        />
        <SettingsItem
          icon={Settings01Icon}
          label="App Settings"
          onPress={() => {}}
        />
      </View>

      <Divider className="my-2" />

      <View className="px-4 py-2">
        <Button onPress={onSignOut} variant="danger">
          <HugeiconsIcon icon={Logout01Icon} size={16} color="#ffffff" />
          <Button.Label>Logout</Button.Label>
        </Button>
      </View>
    </ScrollView>
  );
}
