"use client";

import { Switch } from "@heroui/switch";
import Image from "next/image";
import { useEffect, useState } from "react";
import {
  NOTIFICATION_PLATFORM_ICONS,
  NOTIFICATION_PLATFORM_LABELS,
  NOTIFICATION_PLATFORMS,
  type NotificationPlatform,
} from "@/features/notification/constants";
import { ChatChannelSettings } from "@/features/settings/components/ChatChannelSettings";
import { SettingsPage } from "@/features/settings/components/ui/SettingsPage";
import { SettingsRow } from "@/features/settings/components/ui/SettingsRow";
import { SettingsSection } from "@/features/settings/components/ui/SettingsSection";
import { api } from "@/lib/api/typed";
import { toast } from "@/lib/toast";
import { NotificationsAPI } from "@/services/api/notifications";
import type { PlatformLinks } from "@/types/platform";

export default function NotificationSettings() {
  const [platformLinks, setPlatformLinks] = useState<PlatformLinks>({});
  const [channelPrefs, setChannelPrefs] = useState<
    Record<NotificationPlatform, boolean>
  >({
    telegram: true,
    discord: true,
    whatsapp: true,
    slack: true,
    imessage: true,
  });
  const [loading, setLoading] = useState(true);
  const [togglingPlatform, setTogglingPlatform] = useState<string | null>(null);

  useEffect(() => {
    const fetchAll = async () => {
      setLoading(true);
      try {
        const [linksData, prefs] = await Promise.all([
          api.get("/api/v1/platform-links", { silent: true }),
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
    platform: NotificationPlatform,
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

  const linkedPlatforms = NOTIFICATION_PLATFORMS.filter(
    (platform) => !!platformLinks[platform]?.platformUserId,
  );

  return (
    <SettingsPage>
      {!loading && <ChatChannelSettings linkedPlatforms={linkedPlatforms} />}
      <SettingsSection description="Choose where to receive GAIA notifications.">
        {NOTIFICATION_PLATFORMS.map((platform) => {
          const label = NOTIFICATION_PLATFORM_LABELS[platform];
          const isConnected = !!platformLinks[platform]?.platformUserId;
          return (
            <SettingsRow
              key={platform}
              label={label}
              description={
                isConnected
                  ? "Send notifications to this platform"
                  : "Connect in Linked Accounts to enable"
              }
              icon={
                <Image
                  src={NOTIFICATION_PLATFORM_ICONS[platform]}
                  alt={label}
                  width={36}
                  height={36}
                  className="rounded-xl"
                />
              }
            >
              <Switch
                size="sm"
                isSelected={isConnected ? channelPrefs[platform] : false}
                isDisabled={
                  !isConnected || loading || togglingPlatform === platform
                }
                onValueChange={(enabled) => handleToggle(platform, enabled)}
                aria-label={`Enable ${label} notifications`}
              />
            </SettingsRow>
          );
        })}
      </SettingsSection>
    </SettingsPage>
  );
}
