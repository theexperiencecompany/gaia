import type { ChannelPlatform, ChannelPreferences } from "@gaia/shared/types";
import { Spinner } from "heroui-native";
import { useCallback, useEffect, useState } from "react";
import { Alert, ScrollView, View } from "react-native";
import {
  AppIcon,
  DiscordIcon,
  Notification01Icon,
  SlackIcon,
  TelegramIcon,
  WhatsappIcon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { inAppNotificationsApi } from "@/features/notifications/api/inapp-notifications-api";
import { useResponsive } from "@/lib/responsive";
import { SettingsGroup, SettingsSwitchRow } from "../settings-row";

export function NotificationSection() {
  const { spacing, fontSize } = useResponsive();
  const [channels, setChannels] = useState<ChannelPreferences>({
    telegram: false,
    discord: false,
    whatsapp: false,
    slack: false,
  });
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
        <SettingsSwitchRow
          icon={TelegramIcon}
          iconColor="#2AABEE"
          iconBg="rgba(42,171,238,0.15)"
          title="Telegram"
          subtitle="Receive alerts via your connected Telegram bot"
          value={channels.telegram}
          onValueChange={(val) => {
            void handleToggle("telegram", val);
          }}
          disabled={updatingChannel === "telegram"}
        />
        <SettingsSwitchRow
          icon={DiscordIcon}
          iconColor="#5865F2"
          iconBg="rgba(88,101,242,0.15)"
          title="Discord"
          subtitle="Receive alerts via your connected Discord bot"
          value={channels.discord}
          onValueChange={(val) => {
            void handleToggle("discord", val);
          }}
          disabled={updatingChannel === "discord"}
        />
        <SettingsSwitchRow
          icon={WhatsappIcon}
          iconColor="#25D366"
          iconBg="rgba(37,211,102,0.15)"
          title="WhatsApp"
          subtitle="Receive alerts via your connected WhatsApp bot"
          value={channels.whatsapp}
          onValueChange={(val) => {
            handleToggle("whatsapp", val);
          }}
          disabled={updatingChannel === "whatsapp"}
        />
        <SettingsSwitchRow
          icon={SlackIcon}
          iconColor="#E01E5A"
          iconBg="rgba(224,30,90,0.15)"
          title="Slack"
          subtitle="Receive alerts via your connected Slack workspace"
          value={channels.slack}
          onValueChange={(val) => {
            void handleToggle("slack", val);
          }}
          disabled={updatingChannel === "slack"}
          isLast
        />
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
