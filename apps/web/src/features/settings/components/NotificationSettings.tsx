"use client";

import { Switch } from "@heroui/switch";
import { MailIcon } from "@icons";
import Image from "next/image";
import { useEffect, useMemo, useState } from "react";
import { ChannelPriorityList } from "@/features/briefing/components/ChannelPriorityList";
import {
  NOTIFICATION_PLATFORM_ICONS,
  NOTIFICATION_PLATFORM_LABELS,
  NOTIFICATION_PLATFORMS,
  type NotificationChannelPreference,
  type NotificationPlatform,
} from "@/features/notification/constants";
import { SettingsPage } from "@/features/settings/components/ui/SettingsPage";
import { SettingsRow } from "@/features/settings/components/ui/SettingsRow";
import { SettingsSection } from "@/features/settings/components/ui/SettingsSection";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import { apiService } from "@/lib/api/service";
import { toast } from "@/lib/toast";
import { NotificationsAPI } from "@/services/api/notifications";
import type { PlatformLink } from "@/types/platform";

export default function NotificationSettings() {
  const [platformLinks, setPlatformLinks] = useState<
    Record<string, PlatformLink | null>
  >({});
  const [channelPrefs, setChannelPrefs] = useState<
    Record<NotificationChannelPreference, boolean>
  >({
    telegram: true,
    discord: true,
    whatsapp: true,
    slack: true,
    imessage: true,
    email: true,
  });
  const [loading, setLoading] = useState(true);
  const [togglingPlatform, setTogglingPlatform] = useState<string | null>(null);

  const linkedMap = useMemo(
    () =>
      Object.fromEntries(
        NOTIFICATION_PLATFORMS.map((platform) => [
          platform,
          !!platformLinks[platform]?.platformUserId,
        ]),
      ) as Record<NotificationPlatform, boolean>,
    [platformLinks],
  );

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
    channel: NotificationChannelPreference,
    enabled: boolean,
  ) => {
    setTogglingPlatform(channel);
    try {
      await NotificationsAPI.updateChannelPreference(channel, enabled);
      setChannelPrefs((prev) => ({ ...prev, [channel]: enabled }));
      trackEvent(ANALYTICS_EVENTS.SETTINGS_NOTIFICATIONS_TOGGLED, {
        platform: channel,
        enabled,
      });
    } catch {
      toast.error(`Failed to update ${channel} notification preference`);
    } finally {
      setTogglingPlatform(null);
    }
  };

  return (
    <SettingsPage>
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
        <SettingsRow
          label="Email"
          description="Daily briefings and weekly digests, sent to your account email"
          icon={
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-zinc-800">
              <MailIcon className="h-5 w-5 text-zinc-300" />
            </div>
          }
        >
          <Switch
            size="sm"
            isSelected={channelPrefs.email}
            isDisabled={loading || togglingPlatform === "email"}
            onValueChange={(enabled) => handleToggle("email", enabled)}
            aria-label="Enable email notifications"
          />
        </SettingsRow>
      </SettingsSection>

      <div>
        <p className="mb-2 text-sm font-medium text-zinc-300">
          Where your briefing lands
        </p>
        <p className="mb-3 text-sm text-zinc-500">
          Your daily brief goes to the first connected channel in this order.
        </p>
        <ChannelPriorityList linkedMap={linkedMap} />
      </div>
    </SettingsPage>
  );
}
