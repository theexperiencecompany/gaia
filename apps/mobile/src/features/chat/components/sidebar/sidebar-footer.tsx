import { useRouter } from "expo-router";
import { ActivityIndicator, Image, Pressable, View } from "react-native";
import { AppIcon, ArrowRight01Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useAuth } from "@/features/auth/hooks/use-auth";
import { useResponsive } from "@/lib/responsive";
import { Divider } from "@/shared/components/ui/divider";

const MUTED_COLOR = "#71717a";
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
      <>
        <Divider className="bg-zinc-700/50" />
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
      <Divider className="bg-zinc-700/50" />
      <Pressable
        onPress={() => router.push("/(app)/settings")}
        style={({ pressed }) => ({
          flexDirection: "row",
          alignItems: "center",
          paddingHorizontal: spacing.md,
          paddingVertical: spacing.md,
          gap: spacing.sm + 2,
          opacity: pressed ? 0.7 : 1,
        })}
      >
        <View
          style={{
            width: 36,
            height: 36,
            borderRadius: 18,
            backgroundColor: AVATAR_BG,
            alignItems: "center",
            justifyContent: "center",
            overflow: "hidden",
          }}
        >
          {profilePicture ? (
            <Image
              source={{ uri: profilePicture }}
              style={{ width: 36, height: 36 }}
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
            style={{ fontSize: fontSize.sm, fontWeight: "600" }}
            numberOfLines={1}
          >
            {user?.name || "User"}
          </Text>
          <Text
            style={{
              fontSize: fontSize.xs,
              color: MUTED_COLOR,
              textTransform: "uppercase",
              // medium weight to match design system uppercase label pattern
              fontWeight: "500",
              letterSpacing: 0.7,
            }}
          >
            GAIA Free
          </Text>
        </View>
        <AppIcon icon={ArrowRight01Icon} size={iconSize.sm} color="#71717a" />
      </Pressable>
    </>
  );
}
