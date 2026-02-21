"use client";

import { Switch } from "@heroui/switch";
import Image from "next/image";
import { useEffect, useState } from "react";
import {
  SettingsPage,
  SettingsRow,
  SettingsSection,
} from "@/features/settings/components/ui";
import { apiService } from "@/lib/api";
import { toast } from "@/lib/toast";
import { NotificationsAPI } from "@/services/api/notifications";
import type { PlatformLink } from "@/types/platform";

const NOTIFICATION_PLATFORMS = [
  {
    id: "telegram" as const,
    name: "Telegram",
    image: "/images/icons/macos/telegram.webp",
  },
  {
    id: "discord" as const,
    name: "Discord",
    image: "/images/icons/macos/discord.webp",
  },
];

export default function NotificationSettings() {
  const [platformLinks, setPlatformLinks] = useState<
    Record<string, PlatformLink | null>
  >({});
  const [channelPrefs, setChannelPrefs] = useState<{
    telegram: boolean;
    discord: boolean;
  }>({ telegram: true, discord: true });
  const [loading, setLoading] = useState(true);
  const [togglingPlatform, setTogglingPlatform] = useState<string | null>(null);

  useEffect(() => {
    const fetchAll = async () => {
      setLoading(true);
      try {
        const [linksData, prefs] = await Promise.all([
          apiService.get<{
            platform_links: Record<string, PlatformLink | null>;
          }>("/platform-links", { silent: true }),
          NotificationsAPI.getChannelPreferences(),
        ]);
        setPlatformLinks(linksData.platform_links || {});
        setChannelPrefs(prefs);
      } catch {
        // silently ignore
      } finally {
        setLoading(false);
      }
    };

    fetchAll();
  }, []);

  const handleToggle = async (
    platform: "telegram" | "discord",
    enabled: boolean,
  ) => {
    setTogglingPlatform(platform);
    try {
      await NotificationsAPI.updateChannelPreference(platform, enabled);
      setChannelPrefs((prev) => ({ ...prev, [platform]: enabled }));
    } catch {
      toast.error(`Failed to update ${platform} notification preference`);
    } finally {
      setTogglingPlatform(null);
    }
  };

  return (
    <SettingsPage>
      <SettingsSection description="Choose where to receive GAIA notifications.">
        {NOTIFICATION_PLATFORMS.map((platform) => {
          const isConnected = !!platformLinks[platform.id]?.platformUserId;
          return (
            <SettingsRow
              key={platform.id}
              label={platform.name}
              description={
                isConnected
                  ? "Send notifications to this platform"
                  : "Connect in Linked Accounts to enable"
              }
              icon={
                <Image
                  src={platform.image}
                  alt={platform.name}
                  width={36}
                  height={36}
                  className="rounded-xl"
                />
              }
            >
              <Switch
                size="sm"
                isSelected={isConnected ? channelPrefs[platform.id] : false}
                isDisabled={
                  !isConnected || loading || togglingPlatform === platform.id
                }
                onValueChange={(enabled) => handleToggle(platform.id, enabled)}
                aria-label={`Enable ${platform.name} notifications`}
              />
            </SettingsRow>
          );
        })}
      </SettingsSection>
    </SettingsPage>
  );
}
