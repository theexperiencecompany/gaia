import { useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { Pressable, View } from "react-native";
import { AppIcon, LinkSquare02Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { inAppNotificationsApi } from "@/features/notifications/api/inapp-notifications-api";
import { useResponsive } from "@/lib/responsive";

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
    <View style={{ paddingHorizontal: spacing.md, paddingTop: spacing.sm }}>
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          justifyContent: "space-between",
          gap: spacing.sm,
          borderRadius: moderateScale(12, 0.5),
          backgroundColor: "rgba(255,255,255,0.04)",
          borderWidth: 1,
          borderColor: "rgba(255,255,255,0.07)",
          paddingHorizontal: spacing.md,
          paddingVertical: spacing.sm + 2,
        }}
      >
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            gap: spacing.sm,
            flex: 1,
          }}
        >
          <View
            style={{
              width: 30,
              height: 30,
              borderRadius: 8,
              backgroundColor: "rgba(0,187,255,0.1)",
              alignItems: "center",
              justifyContent: "center",
              flexShrink: 0,
            }}
          >
            <AppIcon icon={LinkSquare02Icon} size={15} color="#00bbff" />
          </View>
          <Text
            style={{
              fontSize: fontSize.xs,
              color: "#8a9099",
              flex: 1,
            }}
          >
            Get notified in the apps you already use
          </Text>
        </View>

        <Pressable
          onPress={() => router.push("/(app)/integrations")}
          style={{
            borderRadius: 8,
            backgroundColor: "rgba(0,187,255,0.12)",
            paddingHorizontal: spacing.sm + 4,
            paddingVertical: 6,
            flexShrink: 0,
          }}
        >
          <Text
            style={{
              fontSize: fontSize.xs,
              color: "#00bbff",
              fontWeight: "600",
            }}
          >
            Connect
          </Text>
        </Pressable>
      </View>
    </View>
  );
}
