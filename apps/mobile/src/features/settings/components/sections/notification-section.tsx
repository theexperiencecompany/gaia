import { Card, Spinner, Switch } from "heroui-native";
import { useCallback, useEffect, useState } from "react";
import { Alert, View } from "react-native";
import { Text } from "@/components/ui/text";
import type { ChannelPreferences } from "@/features/settings/api/settings-api";
import { settingsApi } from "@/features/settings/api/settings-api";
import { useResponsive } from "@/lib/responsive";

interface ChannelRowProps {
  label: string;
  description: string;
  value: boolean;
  onToggle: (val: boolean) => void;
  disabled?: boolean;
}

function ChannelRow({
  label,
  description,
  value,
  onToggle,
  disabled = false,
}: ChannelRowProps) {
  const { fontSize } = useResponsive();
  return (
    <Card variant="secondary" className="rounded-3xl bg-surface">
      <Card.Body className="flex-row items-center gap-4 px-4 py-4">
        <View style={{ flex: 1 }}>
          <Text style={{ fontSize: fontSize.base, fontWeight: "500" }}>
            {label}
          </Text>
          <Text
            style={{ fontSize: fontSize.xs, color: "#8e8e93", marginTop: 2 }}
          >
            {description}
          </Text>
        </View>
        <Switch
          isSelected={value}
          onSelectedChange={onToggle}
          isDisabled={disabled}
        />
      </Card.Body>
    </Card>
  );
}

export function NotificationSection() {
  const { spacing, fontSize } = useResponsive();
  const [channels, setChannels] = useState<ChannelPreferences>({
    telegram: false,
    discord: false,
  });
  const [isLoading, setIsLoading] = useState(true);
  const [updatingChannel, setUpdatingChannel] = useState<
    "telegram" | "discord" | null
  >(null);

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    settingsApi
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
    async (platform: "telegram" | "discord", enabled: boolean) => {
      setUpdatingChannel(platform);
      const previous = channels[platform];
      setChannels((prev) => ({ ...prev, [platform]: enabled }));
      try {
        await settingsApi.updateChannelPreference(platform, enabled);
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
    <View style={{ flex: 1, padding: spacing.md, gap: spacing.md }}>
      <Text style={{ fontSize: fontSize.xs, color: "#8e8e93" }}>
        Control which channels can send you notifications from GAIA.
      </Text>

      <ChannelRow
        label="Telegram"
        description="Receive alerts via your connected Telegram bot."
        value={channels.telegram}
        onToggle={(val) => {
          void handleToggle("telegram", val);
        }}
        disabled={updatingChannel === "telegram"}
      />
      <ChannelRow
        label="Discord"
        description="Receive alerts via your connected Discord bot."
        value={channels.discord}
        onToggle={(val) => {
          void handleToggle("discord", val);
        }}
        disabled={updatingChannel === "discord"}
      />

      <Text
        style={{
          fontSize: fontSize.xs,
          color: "#5a5a5e",
          marginTop: spacing.sm,
        }}
      >
        Connect platforms in{" "}
        <Text style={{ color: "#9fe6ff" }}>Integrations</Text> to enable
        notifications.
      </Text>
    </View>
  );
}
