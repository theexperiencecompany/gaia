import {
  ActivityIndicator,
  Image,
  Pressable,
  TouchableOpacity,
  View,
} from "react-native";
import {
  ArrowDown01Icon,
  HugeiconsIcon,
  InformationCircleIcon,
  Logout01Icon,
  Settings01Icon,
  UserIcon,
} from "@/components/icons";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Text } from "@/components/ui/text";
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

  const getAvatarColor = (email?: string) => {
    if (!email) return "#00aa88";
    const colors = [
      "#00aa88",
      "#0088cc",
      "#8855cc",
      "#cc5588",
      "#cc8855",
      "#55cc88",
    ];
    const hash = email
      .split("")
      .reduce((acc, char) => acc + char.charCodeAt(0), 0);
    return colors[hash % colors.length];
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
    <View className="border-t border-border/20 py-3">
      <TouchableOpacity
        className="flex-row items-center px-6 py-3 gap-3"
        activeOpacity={0.7}
      >
        <HugeiconsIcon icon={InformationCircleIcon} size={20} color="#8e8e93" />
        <Text className="text-foreground text-sm font-medium">
          Need Support?
        </Text>
      </TouchableOpacity>

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Pressable className="flex-row items-center px-6 py-3 gap-3 active:opacity-70">
            {user?.picture ? (
              <Image
                source={{ uri: user.picture }}
                className="w-8 h-8 rounded-full"
              />
            ) : (
              <View
                className="w-8 h-8 rounded-full justify-center items-center"
                style={{ backgroundColor: getAvatarColor(user?.email) }}
              >
                <Text className="text-white text-xs font-bold">
                  {getInitials(user?.name)}
                </Text>
              </View>
            )}
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
          </Pressable>
        </DropdownMenuTrigger>
        <DropdownMenuContent
          className="w-56"
          side="top"
          align="end"
          portalHost="sidebar-footer"
        >
          <DropdownMenuLabel>My Account</DropdownMenuLabel>
          <DropdownMenuSeparator />
          <DropdownMenuGroup>
            <DropdownMenuItem>
              <HugeiconsIcon icon={UserIcon} size={18} color="#8e8e93" />
              <Text>Profile</Text>
            </DropdownMenuItem>
            <DropdownMenuItem>
              <HugeiconsIcon icon={Settings01Icon} size={18} color="#8e8e93" />
              <Text>Settings</Text>
            </DropdownMenuItem>
          </DropdownMenuGroup>
          <DropdownMenuSeparator />
          <DropdownMenuItem variant="destructive" onPress={() => signOut()}>
            <HugeiconsIcon icon={Logout01Icon} size={18} color="#ef4444" />
            <Text className="text-destructive">Log out</Text>
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </View>
  );
}
