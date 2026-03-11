import { useRouter } from "expo-router";
import { Avatar } from "heroui-native";
import { ActivityIndicator, Pressable, View } from "react-native";
import {
  AppIcon,
  Calendar03Icon,
  Flowchart01Icon,
  Logout01Icon,
  Notification01Icon,
  Settings02Icon,
  Wrench01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useAuth } from "@/features/auth";
import { useResponsive } from "@/lib/responsive";

export function SidebarFooter() {
  const { user, isLoading, signOut } = useAuth();
  const router = useRouter();
  const { spacing, fontSize, iconSize } = useResponsive();

  const getInitials = (name?: string) => {
    if (!name) return "U";
    const parts = name.trim().split(" ");
    if (parts.length >= 2) {
      return `${parts[0][0]}${parts[parts.length - 1][0]}`.toUpperCase();
    }
    return name[0].toUpperCase();
  };

  const navItems = [
    {
      icon: Settings02Icon,
      label: "Settings",
      onPress: () => router.push("/(app)/settings"),
    },
    {
      icon: Wrench01Icon,
      label: "Integrations",
      onPress: () => router.push("/(app)/(tabs)/integrations"),
    },
    {
      icon: Flowchart01Icon,
      label: "Workflows",
      onPress: () => router.push("/(app)/(tabs)/workflows"),
    },
    {
      icon: Notification01Icon,
      label: "Notifications",
      onPress: () => router.push("/(app)/(tabs)/notifications"),
    },
    {
      icon: Calendar03Icon,
      label: "Calendar",
      onPress: () => router.push("/(app)/calendar"),
    },
  ];

  const profilePicture = user?.picture;

  if (isLoading) {
    return (
      <View
        style={{
          borderTopWidth: 1,
          borderTopColor: "rgba(255,255,255,0.06)",
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
    <View
      style={{
        borderTopWidth: 1,
        borderTopColor: "rgba(255,255,255,0.06)",
      }}
    >
      <View
        style={{
          flexDirection: "row",
          flexWrap: "wrap",
          paddingHorizontal: spacing.md,
          paddingTop: spacing.sm + 2,
          paddingBottom: spacing.xs,
          gap: 2,
        }}
      >
        {navItems.map((item) => (
          <Pressable
            key={item.label}
            onPress={item.onPress}
            style={({ pressed }) => ({
              flexDirection: "row",
              alignItems: "center",
              paddingHorizontal: spacing.sm,
              paddingVertical: spacing.xs + 2,
              borderRadius: 6,
              gap: 4,
              opacity: pressed ? 0.6 : 1,
            })}
          >
            <AppIcon icon={item.icon} size={iconSize.sm - 2} color="#52525b" />
            <Text
              style={{
                fontSize: fontSize.xs - 1,
                color: "#52525b",
              }}
            >
              {item.label}
            </Text>
          </Pressable>
        ))}
      </View>

      <Pressable
        style={({ pressed }) => ({
          flexDirection: "row",
          alignItems: "center",
          paddingHorizontal: spacing.md,
          paddingVertical: spacing.sm,
          gap: spacing.sm + 2,
          opacity: pressed ? 0.7 : 1,
        })}
        onPress={() => router.push("/(app)/settings")}
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
              color: "#52525b",
              textTransform: "uppercase",
              fontWeight: "600",
              letterSpacing: 1,
            }}
          >
            GAIA Free
          </Text>
        </View>
        <Pressable
          onPress={signOut}
          style={({ pressed }) => ({
            padding: spacing.xs + 2,
            opacity: pressed ? 0.6 : 1,
          })}
          hitSlop={8}
        >
          <AppIcon icon={Logout01Icon} size={iconSize.sm} color="#ef4444" />
        </Pressable>
      </Pressable>
    </View>
  );
}
