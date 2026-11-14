import type { ChannelPlatform, ChannelPreferences } from "@gaia/shared/types";
import { NOTIFICATION_CHANNELS } from "@gaia/shared/types";
import { Spinner } from "heroui-native";
import { useCallback, useEffect, useState } from "react";
import { Alert, ScrollView, View } from "react-native";
import { AppIcon, Notification01Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { inAppNotificationsApi } from "@/features/notifications/api/inapp-notifications-api";
import { NOTIFICATION_CHANNEL_META } from "@/features/notifications/constants/channels";
import { useResponsive } from "@/lib/responsive";
import { SettingsGroup, SettingsSwitchRow } from "../settings-row";

export function NotificationSection() {
  const { spacing, fontSize } = useResponsive();
  const [channels, setChannels] = useState<ChannelPreferences>(
    () =>
      Object.fromEntries(
        NOTIFICATION_CHANNELS.map((channel) => [channel, false]),
      ) as ChannelPreferences,
  );
  const [isLoading, setIsLoading] = useState(true);
  const [updatingChannel, setUpdatingChannel] =
    useState<ChannelPlatform | null>(null);

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    inAppNotificationsApi
      .getChannelPreferences()
      .then((data) => {
        if (!cancelled) setChannels(data);
      })
      .catch(() => {
        if (!cancelled)
          Alert.alert("Error", "Failed to load notification settings.");
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleToggle = useCallback(
    async (platform: ChannelPlatform, enabled: boolean) => {
      setUpdatingChannel(platform);
      const previous = channels[platform];
      setChannels((prev) => ({ ...prev, [platform]: enabled }));
      try {
        await inAppNotificationsApi.updateChannelPreference(platform, enabled);
      } catch {
        setChannels((prev) => ({ ...prev, [platform]: previous }));
        Alert.alert("Error", "Failed to update notification preference.");
      } finally {
        setUpdatingChannel(null);
      }
    },
    [channels],
  );

  if (isLoading) {
    return (
      <View style={{ flex: 1, alignItems: "center", justifyContent: "center" }}>
        <Spinner />
      </View>
    );
  }

  return (
    <ScrollView
      showsVerticalScrollIndicator={false}
      contentContainerStyle={{
        padding: spacing.md,
        gap: spacing.lg,
        paddingBottom: 40,
      }}
    >
      <Text
        style={{
          fontSize: fontSize.xs,
          color: "#71717a",
          lineHeight: fontSize.xs * 1.5,
        }}
      >
        Control which channels can send you notifications from GAIA.
      </Text>

      <SettingsGroup label="Notification Channels">
        {NOTIFICATION_CHANNELS.map((channel, idx) => {
          const meta = NOTIFICATION_CHANNEL_META[channel];
          return (
            <SettingsSwitchRow
              key={channel}
              icon={meta.icon}
              iconColor={meta.iconColor}
              iconBg={meta.iconBg}
              title={meta.name}
              subtitle={meta.description}
              value={channels[channel]}
              onValueChange={(val) => {
                void handleToggle(channel, val);
              }}
              disabled={updatingChannel === channel}
              isLast={idx === NOTIFICATION_CHANNELS.length - 1}
            />
          );
        })}
      </SettingsGroup>

      <View
        style={{
          flexDirection: "row",
          alignItems: "flex-start",
          gap: spacing.xs,
          backgroundColor: "rgba(22,193,255,0.06)",
          borderRadius: 12,
          padding: spacing.md,
        }}
      >
        <AppIcon icon={Notification01Icon} size={14} color="#16c1ff" />
        <Text
          style={{
            flex: 1,
            fontSize: fontSize.xs,
            color: "#71717a",
            lineHeight: fontSize.xs * 1.5,
          }}
        >
          Connect platforms in{" "}
          <Text style={{ color: "#9fe6ff" }}>Integrations</Text> to enable
          notifications.
        </Text>
      </View>
    </ScrollView>
  );
}
