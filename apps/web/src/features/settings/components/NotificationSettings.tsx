"use client";

import { EMAIL_CHANNEL_DESCRIPTION, NOTIFICATION_CHANNELS } from "@gaia/shared";
import type { ChannelPlatform, ChannelPreferences } from "@gaia/shared/types";
import { Button } from "@heroui/button";
import { Switch } from "@heroui/switch";
import { Link01Icon } from "@icons";
import Image from "next/image";
import Link from "next/link";
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

const PLATFORM_NAME_LIST = new Intl.ListFormat("en", {
  style: "long",
  type: "conjunction",
});

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
  // Email reaches the user through their GAIA address; a bot platform only
  // once it is linked, so unlinked ones fold into a single row below.
  const switchableChannels = NOTIFICATION_CHANNELS.filter(
    (channel) =>
      !isBotPlatform(channel) || !!platformLinks[channel]?.platformUserId,
  );
  const unlinkedChannels = NOTIFICATION_CHANNELS.filter(
    (channel) =>
      isBotPlatform(channel) && !platformLinks[channel]?.platformUserId,
  );

  return (
    <SettingsPage>
      <QuietHoursSettings />
      {!loading && <ChatChannelSettings linkedPlatforms={linkedPlatforms} />}
      <SettingsSection
        title="Notification channels"
        description="Choose where to receive GAIA notifications."
      >
        {switchableChannels.map((channel) => {
          const label = NOTIFICATION_CHANNEL_LABELS[channel];
          return (
            <SettingsRow
              key={channel}
              label={label}
              description={
                channel === "email"
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
                isSelected={!!channelPrefs && channelPrefs[channel]}
                isDisabled={
                  loading || !channelPrefs || togglingPlatform === channel
                }
                onValueChange={(enabled) => handleToggle(channel, enabled)}
                aria-label={`Enable ${label} notifications`}
              />
            </SettingsRow>
          );
        })}
        {!loading && unlinkedChannels.length > 0 && (
          <SettingsRow
            label={PLATFORM_NAME_LIST.format(
              unlinkedChannels.map(
                (channel) => NOTIFICATION_CHANNEL_LABELS[channel],
              ),
            )}
            description="Link them to get notifications there too."
            icon={
              <div className="flex size-9 items-center justify-center rounded-xl bg-zinc-800">
                <Link01Icon className="size-4 text-zinc-400" />
              </div>
            }
          >
            <Link
              href="/settings/linked-accounts"
              className="text-sm text-primary"
            >
              Linked Accounts
            </Link>
          </SettingsRow>
        )}
      </SettingsSection>
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
