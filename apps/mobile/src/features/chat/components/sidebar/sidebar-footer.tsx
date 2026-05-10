import { useRouter } from "expo-router";
import { ActivityIndicator, Image, Pressable, View } from "react-native";
import { AppIcon, ArrowRight01Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useAuth } from "@/features/auth/hooks/use-auth";
import { useSidebar } from "@/features/chat/hooks/sidebar-context";
import { useResponsive } from "@/lib/responsive";

const AVATAR_BG = "#27272a";
const AVATAR_ACCENT = "#00bbff";

export function SidebarFooter() {
  const { user, isLoading } = useAuth();
  const router = useRouter();
  const { closeSidebar } = useSidebar();
  const { spacing, fontSize, iconSize } = useResponsive();

  const handleOpenSettings = () => {
    closeSidebar();
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

  const profilePicture = user?.picture;

  if (isLoading) {
    return (
      <View
        style={{
          paddingVertical: spacing.md,
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <ActivityIndicator size="small" color={AVATAR_ACCENT} />
      </View>
    );
  }

  return (
    <Pressable
      onPress={handleOpenSettings}
      style={({ pressed }) => ({
        flexDirection: "row",
        alignItems: "center",
        paddingHorizontal: spacing.sm + 4,
        paddingVertical: spacing.sm + 2,
        gap: spacing.sm + 2,
        borderRadius: 12,
        marginHorizontal: spacing.xs,
        marginBottom: 6,
        backgroundColor: pressed ? "#27272a" : "transparent",
      })}
    >
      <View
        style={{
          width: 32,
          height: 32,
          borderRadius: 16,
          backgroundColor: AVATAR_BG,
          alignItems: "center",
          justifyContent: "center",
          overflow: "hidden",
        }}
      >
        {profilePicture ? (
          <Image
            source={{ uri: profilePicture }}
            style={{ width: 32, height: 32 }}
          />
        ) : (
          <Text
            style={{
              color: AVATAR_ACCENT,
              fontWeight: "600",
              fontSize: fontSize.sm,
            }}
          >
            {getInitials(user?.name)}
          </Text>
        )}
      </View>
      <View style={{ flex: 1 }}>
        <Text
          style={{
            fontSize: fontSize.md,
            fontWeight: "500",
            color: "#e4e4e7",
          }}
          numberOfLines={1}
        >
          {user?.name || "User"}
        </Text>
        <Text style={{ fontSize: 12, color: "#71717a", marginTop: 1 }}>
          GAIA Free
        </Text>
      </View>
      <AppIcon icon={ArrowRight01Icon} size={iconSize.md} color="#71717a" />
    </Pressable>
  );
}
