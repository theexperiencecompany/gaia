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
        backgroundColor: "#101318",
        padding: spacing.md,
        gap: spacing.sm,
      }}
    >
      <Text style={{ fontSize: fontSize.sm, color: "#e8ebef" }}>
        Connect your accounts to unlock richer notifications.
      </Text>
      <Text style={{ fontSize: fontSize.xs, color: "#8a9099" }}>
        Link Telegram, Discord, or Slack from integrations.
      </Text>
      <Pressable
        onPress={() => router.push("/(app)/integrations")}
        style={{
          alignSelf: "flex-start",
          borderRadius: 999,
          paddingHorizontal: spacing.md,
          paddingVertical: spacing.xs,
          backgroundColor: "rgba(22,193,255,0.18)",
        }}
      >
        <Text style={{ fontSize: fontSize.xs, color: "#9fe6ff" }}>
          Open linked accounts
        </Text>
      </Pressable>
    </View>
  );
}
