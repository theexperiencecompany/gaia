import { useRouter } from "expo-router";
import { ActivityIndicator, Image, Pressable, View } from "react-native";
import { AppIcon, Logout01Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useAuth } from "@/features/auth/hooks/use-auth";
import { useResponsive } from "@/lib/responsive";

const DIVIDER_COLOR = "#27272a";
const MUTED_COLOR = "#52525b";
const AVATAR_BG = "#18181b";
const AVATAR_ACCENT = "#00bbff";

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

  const profilePicture = user?.picture;

  if (isLoading) {
    return (
      <>
        <View style={{ height: 1, backgroundColor: DIVIDER_COLOR }} />
        <View
          style={{
            paddingVertical: spacing.lg,
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <ActivityIndicator size="small" color={AVATAR_ACCENT} />
        </View>
      </>
    );
  }

  return (
    <>
      <View style={{ height: 1, backgroundColor: DIVIDER_COLOR }} />
      <Pressable
        onPress={() => router.push("/(app)/settings")}
        style={({ pressed }) => ({
          flexDirection: "row",
          alignItems: "center",
          paddingHorizontal: spacing.md,
          paddingVertical: spacing.sm + 2,
          gap: spacing.sm + 2,
          opacity: pressed ? 0.6 : 1,
        })}
      >
        <View
          style={{
            width: 34,
            height: 34,
            borderRadius: 17,
            backgroundColor: AVATAR_BG,
            alignItems: "center",
            justifyContent: "center",
            overflow: "hidden",
          }}
        >
          {profilePicture ? (
            <Image
              source={{ uri: profilePicture }}
              style={{ width: 34, height: 34 }}
            />
          ) : (
            <Text style={{ color: AVATAR_ACCENT, fontWeight: "600" }}>
              {getInitials(user?.name)}
            </Text>
          )}
        </View>
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
              color: MUTED_COLOR,
              textTransform: "uppercase",
              fontWeight: "600",
              letterSpacing: 0.8,
            }}
          >
            GAIA Free
          </Text>
        </View>
        <Pressable
          onPress={signOut}
          hitSlop={8}
          style={({ pressed }) => ({
            padding: spacing.xs + 2,
            opacity: pressed ? 0.5 : 1,
          })}
        >
          <AppIcon icon={Logout01Icon} size={iconSize.sm} color="#ef4444" />
        </Pressable>
      </Pressable>
    </>
  );
}
