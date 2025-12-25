import { ActivityIndicator, Image, Text, View } from "react-native";
import {
  ArrowDown01Icon,
  HugeiconsIcon,
  InformationCircleIcon,
  Logout01Icon,
  Settings01Icon,
  UserIcon,
} from "@/components/icons";
import {
  Avatar,
  Button,
  Divider,
  Popover,
  PressableFeedback,
} from "heroui-native";
import { useAuth } from "@/features/auth";

export function SidebarFooter() {
  const { user, isLoading, signOut } = useAuth();

  const getInitials = (name?: string) => {
    if (!name) return "U";
    const parts = name.trim().split(" ");
    if (parts.length >= 2) {
      return `${parts[0][0]}${parts[parts.length - 1][0]}`.toUpperCase();
    }
    return name[0].toUpperCase();
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
    <View
      style={{
        borderTopWidth: 1,
        borderTopColor: "#2a2a2a",
        paddingVertical: 12,
      }}
    >
      <PressableFeedback>
        <View className="flex-row items-center px-6 py-3 gap-3">
          <HugeiconsIcon
            icon={InformationCircleIcon}
            size={20}
            color="#8e8e93"
          />
          <Text className="text-foreground text-sm font-medium">
            Need Support?
          </Text>
        </View>
      </PressableFeedback>

      <Popover>
        <Popover.Trigger>
          <PressableFeedback>
            <View className="flex-row items-center px-6 py-3 gap-3">
              <Avatar alt="user" size="sm" color="accent">
                {user?.picture ? (
                  <Avatar.Image source={{ uri: user.picture }} />
                ) : null}
                <Avatar.Fallback>{getInitials(user?.name)}</Avatar.Fallback>
              </Avatar>
              <View className="flex-1">
                <Text
                  className="text-foreground text-sm font-semibold"
                  numberOfLines={1}
                >
                  {user?.name || "User"}
                </Text>
                <Text className="text-muted-foreground text-[9px] uppercase font-bold tracking-[0.15em] opacity-60">
                  GAIA Free
                </Text>
              </View>
              <HugeiconsIcon icon={ArrowDown01Icon} size={16} color="#8e8e93" />
            </View>
          </PressableFeedback>
        </Popover.Trigger>
        <Popover.Portal>
          <Popover.Overlay />
          <Popover.Content placement="top" width={224}>
            <Popover.Title>My Account</Popover.Title>
            <Divider className="my-2" />
            <View className="gap-1">
              <Button variant="ghost" className="justify-start">
                <HugeiconsIcon icon={UserIcon} size={18} color="#8e8e93" />
                <Button.Label>Profile</Button.Label>
              </Button>
              <Button variant="ghost" className="justify-start">
                <HugeiconsIcon
                  icon={Settings01Icon}
                  size={18}
                  color="#8e8e93"
                />
                <Button.Label>Settings</Button.Label>
              </Button>
            </View>
            <Divider className="my-2" />
            <Button variant="danger" onPress={() => signOut()}>
              <HugeiconsIcon icon={Logout01Icon} size={18} color="#ffffff" />
              <Button.Label>Log out</Button.Label>
            </Button>
          </Popover.Content>
        </Popover.Portal>
      </Popover>
    </View>
  );
}
