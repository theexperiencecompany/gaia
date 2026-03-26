import { useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { Button, Card } from "heroui-native";
import { View } from "react-native";
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
    <Card
      className="mx-4 mt-4 rounded-2xl border border-white/10 bg-[#171920]"
      style={{ borderRadius: moderateScale(14, 0.5) }}
    >
      <Card.Body className="px-4 py-4">
        <View style={{ gap: spacing.sm }}>
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
            Connect Telegram and Discord to receive GAIA notifications outside
            the app.
          </Text>
        </View>

        <Button
          size="sm"
          variant="tertiary"
          onPress={() => router.push("/(app)/(tabs)/integrations")}
          className="mt-3 self-start bg-primary/15 px-4"
        >
          <Button.Label className="text-primary text-xs">
            Connect platforms
          </Button.Label>
        </Button>
      </Card.Body>
    </Card>
  );
}
