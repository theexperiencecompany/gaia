import { useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { Pressable, View } from "react-native";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { inAppNotificationsApi } from "../api";

export function NotificationConnectBanner() {
  const router = useRouter();
  const { spacing, fontSize, moderateScale } = useResponsive();

  const { data } = useQuery({
    queryKey: ["platform-links"],
    queryFn: inAppNotificationsApi.getPlatformLinks,
    staleTime: 5 * 60 * 1000,
  });

  const connectedCount = Object.keys(data?.platform_links ?? {}).length;

  if (connectedCount > 0) {
    return null;
  }

  return (
    <View
      style={{
        marginHorizontal: spacing.md,
        marginTop: spacing.md,
        borderRadius: moderateScale(14, 0.5),
        borderWidth: 1,
        borderColor: "rgba(255,255,255,0.08)",
        backgroundColor: "rgba(255,255,255,0.04)",
        padding: spacing.md,
        gap: spacing.sm,
      }}
    >
      <Text
        style={{
          fontSize: fontSize.sm,
          fontWeight: "500",
          color: "#e8ebef",
        }}
      >
        Stay notified on your devices
      </Text>
      <Text style={{ fontSize: fontSize.xs, color: "#8a9099" }}>
        Connect Telegram and Discord to receive GAIA notifications outside the
        app.
      </Text>
      <Pressable
        onPress={() => router.push("/(app)/(tabs)/integrations")}
        style={{
          alignSelf: "flex-start",
          borderRadius: 8,
          paddingHorizontal: spacing.md,
          paddingVertical: 6,
          backgroundColor: "rgba(22,193,255,0.12)",
          marginTop: 4,
        }}
      >
        <Text
          style={{
            fontSize: fontSize.xs,
            color: "#16c1ff",
            fontWeight: "500",
          }}
        >
          Connect platforms
        </Text>
      </Pressable>
    </View>
  );
}
