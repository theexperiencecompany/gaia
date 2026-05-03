import { useRouter } from "expo-router";
import { ActivityIndicator, Image, Pressable, View } from "react-native";
import { AppIcon, ArrowRight01Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useAuth } from "@/features/auth/hooks/use-auth";
import { useResponsive } from "@/lib/responsive";

const AVATAR_BG = "#27272a";
const AVATAR_ACCENT = "#00bbff";

export function SidebarFooter() {
  const { user, isLoading } = useAuth();
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
      onPress={() => router.push("/(app)/settings")}
      style={({ pressed }) => ({
        flexDirection: "row",
        alignItems: "center",
        paddingHorizontal: spacing.sm + 4,
        paddingVertical: spacing.sm,
        gap: spacing.sm,
        borderRadius: 12,
        marginHorizontal: spacing.xs,
        marginBottom: 4,
        backgroundColor: pressed ? "#27272a" : "transparent",
      })}
    >
      <View
        style={{
          width: 28,
          height: 28,
          borderRadius: 14,
          backgroundColor: AVATAR_BG,
          alignItems: "center",
          justifyContent: "center",
          overflow: "hidden",
        }}
      >
        {profilePicture ? (
          <Image
            source={{ uri: profilePicture }}
            style={{ width: 28, height: 28 }}
          />
        ) : (
          <Text
            style={{
              color: AVATAR_ACCENT,
              fontWeight: "600",
              fontSize: fontSize.xs,
            }}
          >
            {getInitials(user?.name)}
          </Text>
        )}
      </View>
      <View style={{ flex: 1 }}>
        <Text
          style={{
            fontSize: fontSize.sm,
            fontWeight: "500",
            color: "#e4e4e7",
          }}
          numberOfLines={1}
        >
          {user?.name || "User"}
        </Text>
        <Text style={{ fontSize: 11, color: "#71717a" }}>GAIA Free</Text>
      </View>
      <AppIcon icon={ArrowRight01Icon} size={iconSize.sm} color="#71717a" />
    </Pressable>
  );
}
