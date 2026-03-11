import { BottomSheetScrollView } from "@gorhom/bottom-sheet";
import { useRouter } from "expo-router";
import { Avatar } from "heroui-native";
import { forwardRef, useImperativeHandle, useState } from "react";
import { Linking, Pressable, View } from "react-native";
import {
  type AnyIcon,
  AppIcon,
  ArrowRight01Icon,
  BookOpen01Icon,
  BrainIcon,
  ChartLineData01Icon,
  CustomerSupportIcon,
  DiscordIcon,
  Download04Icon,
  KeyboardIcon,
  Logout01Icon,
  MagicWand01Icon,
  Settings01Icon,
  Settings02Icon,
  TwitterIcon,
  UserCircleIcon,
  UserIcon,
  WhatsappIcon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import type { UserInfo } from "@/features/auth";
import { BottomSheet } from "@/shared/components/ui/bottom-sheet";

interface SettingsBottomSheetProps {
  user: UserInfo | null;
  onSignOut: () => void;
}

interface SettingsItemProps {
  icon: AnyIcon;
  label: string;
  onPress: () => void;
  iconColor?: string;
  labelColor?: string;
  showArrow?: boolean;
}

function SettingsItem({
  icon,
  label,
  onPress,
  iconColor = "#a1a1aa",
  labelColor,
  showArrow = false,
}: SettingsItemProps) {
  return (
    <Pressable
      onPress={onPress}
      className="flex-row items-center py-3 active:opacity-60"
    >
      <AppIcon icon={icon} size={20} color={iconColor} />
      <Text
        className="flex-1 text-[15px] ml-3"
        style={labelColor ? { color: labelColor } : undefined}
      >
        {label}
      </Text>
      {showArrow && (
        <AppIcon icon={ArrowRight01Icon} size={16} color="#48484a" />
      )}
    </Pressable>
  );
}

function SectionLabel({ children }: { children: string }) {
  return (
    <Text className="text-xs text-muted pt-4 pb-2 uppercase tracking-wider">
      {children}
    </Text>
  );
}

function Divider() {
  return <View className="h-px bg-white/5 my-1" />;
}

export const SettingsBottomSheet = forwardRef<
  { present: () => void; dismiss: () => void },
  SettingsBottomSheetProps
>(({ user, onSignOut }, ref) => {
  const [isOpen, setIsOpen] = useState(false);
  const router = useRouter();

  useImperativeHandle(ref, () => ({
    present: () => setIsOpen(true),
    dismiss: () => setIsOpen(false),
  }));

  const handleOpenSettingsPage = () => {
    setIsOpen(false);
    router.push("/(app)/settings");
  };

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
    <BottomSheet isOpen={isOpen} onOpenChange={setIsOpen}>
      <BottomSheet.Portal>
        <BottomSheet.Overlay />
        <BottomSheet.Content
          snapPoints={["80%"]}
          enablePanDownToClose
          backgroundStyle={{ backgroundColor: "#141414" }}
          handleIndicatorStyle={{ backgroundColor: "#3a3a3c", width: 40 }}
        >
          <BottomSheetScrollView
            showsVerticalScrollIndicator={false}
            contentContainerStyle={{ paddingHorizontal: 20, paddingBottom: 40 }}
          >
            {/* User Profile */}
            <Pressable className="flex-row items-center py-3 active:opacity-60">
              <Avatar alt="user" size="md" color="accent">
                {user?.picture ? (
                  <Avatar.Image source={{ uri: user.picture }} />
                ) : null}
                <Avatar.Fallback>{getInitials(user?.name)}</Avatar.Fallback>
              </Avatar>
              <View className="flex-1 ml-3">
                <Text className="font-semibold text-[15px]" numberOfLines={1}>
                  {user?.name || "User"}
                </Text>
                <Text className="text-xs text-muted" numberOfLines={1}>
                  {user?.email || ""}
                </Text>
              </View>
            </Pressable>

            <Divider />

            {/* Upgrade to Pro */}
            <Pressable
              className="flex-row items-center py-3 active:opacity-60"
              onPress={() => openLink("https://gaia.com/pricing")}
            >
              <AppIcon icon={MagicWand01Icon} size={20} color="#00bbff" />
              <Text className="ml-3 text-[15px]" style={{ color: "#00bbff" }}>
                Upgrade to Pro
              </Text>
            </Pressable>

            {/* Settings Section */}
            <SectionLabel>Settings</SectionLabel>
            <SettingsItem
              icon={UserIcon}
              label="Profile Card"
              onPress={() => {}}
            />
            <SettingsItem
              icon={UserCircleIcon}
              label="Account"
              onPress={() => {}}
            />
            <SettingsItem
              icon={ChartLineData01Icon}
              label="Usage"
              onPress={() => {}}
            />
            <SettingsItem
              icon={Settings02Icon}
              label="Preferences"
              onPress={() => {}}
            />
            <SettingsItem
              icon={BrainIcon}
              label="Memories"
              onPress={() => {}}
            />
            <SettingsItem
              icon={KeyboardIcon}
              label="Keyboard Shortcuts"
              onPress={() => {}}
            />

            {/* Community Section */}
            <SectionLabel>Community</SectionLabel>
            <SettingsItem
              icon={TwitterIcon}
              label="Follow Us"
              iconColor="#1DA1F2"
              labelColor="#1DA1F2"
              onPress={() => openLink("https://twitter.com/gaia")}
            />
            <SettingsItem
              icon={DiscordIcon}
              label="Join Discord"
              iconColor="#5865F2"
              labelColor="#5865F2"
              onPress={() => openLink("https://discord.gg/gaia")}
            />
            <SettingsItem
              icon={WhatsappIcon}
              label="Join WhatsApp"
              iconColor="#25D366"
              labelColor="#25D366"
              onPress={() => openLink("https://chat.whatsapp.com/gaia")}
            />

            <Divider />

            {/* More Items */}
            <SettingsItem
              icon={Download04Icon}
              label="Download for Mobile"
              showArrow
              onPress={() => {}}
            />
            <SettingsItem
              icon={BookOpen01Icon}
              label="Resources"
              showArrow
              onPress={() => openLink("https://gaia.com/resources")}
            />
            <SettingsItem
              icon={CustomerSupportIcon}
              label="Support"
              showArrow
              onPress={() => openLink("https://gaia.com/support")}
            />
            <SettingsItem
              icon={Settings01Icon}
              label="Settings"
              onPress={handleOpenSettingsPage}
            />

            {/* Sign Out */}
            <SettingsItem
              icon={Logout01Icon}
              label="Sign Out"
              iconColor="#ef4444"
              labelColor="#ef4444"
              onPress={onSignOut}
            />
          </BottomSheetScrollView>
        </BottomSheet.Content>
      </BottomSheet.Portal>
    </BottomSheet>
  );
});

SettingsBottomSheet.displayName = "SettingsBottomSheet";
