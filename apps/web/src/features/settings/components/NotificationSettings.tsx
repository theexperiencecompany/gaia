"use client";

import { EMAIL_CHANNEL_DESCRIPTION, NOTIFICATION_CHANNELS } from "@gaia/shared";
import type { ChannelPlatform, ChannelPreferences } from "@gaia/shared/types";
import { Button } from "@heroui/button";
import { Switch } from "@heroui/switch";
import Image from "next/image";
import { useCallback, useEffect, useState } from "react";
import { isBotPlatform } from "@/config/botPlatforms";
import {
  NOTIFICATION_CHANNEL_ICONS,
  NOTIFICATION_CHANNEL_LABELS,
  NOTIFICATION_PLATFORMS,
} from "@/features/notification/constants";
import { ChatChannelSettings } from "@/features/settings/components/ChatChannelSettings";
import { QuietHoursSettings } from "@/features/settings/components/QuietHoursSettings";
import { SettingsPage } from "@/features/settings/components/ui/SettingsPage";
import { SettingsRow } from "@/features/settings/components/ui/SettingsRow";
import { SettingsSection } from "@/features/settings/components/ui/SettingsSection";
import { api } from "@/lib/api/typed";
import { toast } from "@/lib/toast";
import { NotificationsAPI } from "@/services/api/notifications";
import type { PlatformLinks } from "@/types/platform";

export default function NotificationSettings() {
  const [platformLinks, setPlatformLinks] = useState<PlatformLinks>({});
  // Null until the stored preferences load. There is no safe placeholder: an
  // all-true stand-in renders a channel the user switched off as enabled, and
  // toggling from that reading writes the wrong value back.
  const [channelPrefs, setChannelPrefs] = useState<ChannelPreferences | null>(
    null,
  );
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [togglingPlatform, setTogglingPlatform] = useState<string | null>(null);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    setLoadFailed(false);
    try {
      const [linksData, prefs] = await Promise.all([
        api.get("/api/v1/platform-links", { silent: true }),
        NotificationsAPI.getChannelPreferences(),
      ]);
      setPlatformLinks(linksData.platform_links || {});
      setChannelPrefs(prefs);
    } catch {
      setLoadFailed(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchAll();
  }, [fetchAll]);

  const handleToggle = async (channel: ChannelPlatform, enabled: boolean) => {
    setTogglingPlatform(channel);
    try {
      await NotificationsAPI.updateChannelPreference(channel, enabled);
      setChannelPrefs((prev) =>
        prev ? { ...prev, [channel]: enabled } : prev,
      );
    } catch {
      toast.error(`Failed to update ${channel} notification preference`);
    } finally {
      setTogglingPlatform(null);
    }
  };

  if (loadFailed) {
    return (
      <SettingsPage>
        <PreferencesError onRetry={() => void fetchAll()} />
      </SettingsPage>
    );
  }

  const linkedPlatforms = NOTIFICATION_PLATFORMS.filter(
    (platform) => !!platformLinks[platform]?.platformUserId,
  );

  return (
    <SettingsPage>
      {!loading && <ChatChannelSettings linkedPlatforms={linkedPlatforms} />}
      <SettingsSection description="Choose where to receive GAIA notifications.">
        {NOTIFICATION_CHANNELS.map((channel) => {
          const label = NOTIFICATION_CHANNEL_LABELS[channel];
          // Only bot platforms need a linked account; email reaches the user
          // through the address on their GAIA account.
          const needsLink = isBotPlatform(channel);
          const isAvailable =
            !needsLink || !!platformLinks[channel]?.platformUserId;
          return (
            <SettingsRow
              key={channel}
              label={label}
              description={
                !isAvailable
                  ? "Connect in Linked Accounts to enable"
                  : channel === "email"
                    ? EMAIL_CHANNEL_DESCRIPTION
                    : "Send notifications to this channel"
              }
              icon={
                <Image
                  src={NOTIFICATION_CHANNEL_ICONS[channel]}
                  alt={label}
                  width={36}
                  height={36}
                  className="rounded-xl"
                />
              }
            >
              <Switch
                size="sm"
                isSelected={
                  isAvailable && !!channelPrefs && channelPrefs[channel]
                }
                isDisabled={
                  !isAvailable ||
                  loading ||
                  !channelPrefs ||
                  togglingPlatform === channel
                }
                onValueChange={(enabled) => handleToggle(channel, enabled)}
                aria-label={`Enable ${label} notifications`}
              />
            </SettingsRow>
          );
        })}
      </SettingsSection>
      <QuietHoursSettings />
    </SettingsPage>
  );
}

/**
 * A failed preferences load is a settled failure, not a slow one. Showing the
 * switches anyway would render defaults as if they were the user's stored
 * choices, so the whole page waits behind a retry instead.
 */
function PreferencesError({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col items-center gap-3 rounded-2xl bg-zinc-900/60 p-10 text-center">
      <p className="text-sm font-medium text-zinc-200">
        Couldn&apos;t load your notification settings
      </p>
      <p className="max-w-sm text-xs text-zinc-500">
        Your channels are unchanged — this page just couldn&apos;t reach them.
        Try again in a moment.
      </p>
      <Button
        size="sm"
        color="primary"
        variant="flat"
        radius="full"
        className="mt-1 font-medium"
        onPress={onRetry}
      >
        Try again
      </Button>
    </div>
  );
}
