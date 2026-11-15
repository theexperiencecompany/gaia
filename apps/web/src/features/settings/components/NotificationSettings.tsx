"use client";

import { EMAIL_CHANNEL_DESCRIPTION } from "@gaia/shared";
import type { ChannelPlatform, ChannelPreferences } from "@gaia/shared/types";
import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Select, SelectItem } from "@heroui/select";
import { Switch } from "@heroui/switch";
import Image from "next/image";
import { type ReactNode, useCallback, useEffect, useState } from "react";
import { PhoneLinkModal } from "@/components/shared/PhoneLinkModal";
import { isBotPlatform } from "@/config/botPlatforms";
import {
  NOTIFICATION_CHANNEL_ICONS,
  NOTIFICATION_CHANNEL_LABELS,
  NOTIFICATION_PLATFORMS,
} from "@/features/notification/constants";
import { QuietHoursSettings } from "@/features/settings/components/QuietHoursSettings";
import { SettingsPage } from "@/features/settings/components/ui/SettingsPage";
import { SettingsRow } from "@/features/settings/components/ui/SettingsRow";
import { SettingsSection } from "@/features/settings/components/ui/SettingsSection";
import { useChatChannelSettings } from "@/features/settings/hooks/useChatChannelSettings";
import { usePlatformLinks } from "@/features/settings/hooks/usePlatformLinks";
import { toast } from "@/lib/toast";
import { NotificationsAPI } from "@/services/api/notifications";

export default function NotificationSettings() {
  // Null until the stored preferences load. There is no safe placeholder: an
  // all-true stand-in renders a channel the user switched off as enabled, and
  // toggling from that reading writes the wrong value back.
  const [channelPrefs, setChannelPrefs] = useState<ChannelPreferences | null>(
    null,
  );
  const [prefsFailed, setPrefsFailed] = useState(false);
  const [togglingChannel, setTogglingChannel] =
    useState<ChannelPlatform | null>(null);
  const {
    links,
    loadFailed: linksFailed,
    refetch: refetchLinks,
    isLoading: linksLoading,
    isLinked,
    linkedAs,
    isLockedBehindPro,
    connectingPlatform,
    connect,
    phoneLinkModal,
  } = usePlatformLinks();
  const linkedPlatforms = NOTIFICATION_PLATFORMS.filter(isLinked);
  const unlinkedPlatforms = NOTIFICATION_PLATFORMS.filter(
    (platform) => !isLinked(platform),
  );
  const { linkedOrder, saving, putFirst } =
    useChatChannelSettings(linkedPlatforms);

  const fetchPrefs = useCallback(async () => {
    setPrefsFailed(false);
    try {
      setChannelPrefs(await NotificationsAPI.getChannelPreferences());
    } catch {
      setPrefsFailed(true);
    }
  }, []);

  useEffect(() => {
    void fetchPrefs();
  }, [fetchPrefs]);

  const handleToggle = async (channel: ChannelPlatform, enabled: boolean) => {
    setTogglingChannel(channel);
    try {
      await NotificationsAPI.updateChannelPreference(channel, enabled);
      setChannelPrefs((prev) =>
        prev ? { ...prev, [channel]: enabled } : prev,
      );
    } catch {
      toast.error(`Failed to update ${channel} notification preference`);
    } finally {
      setTogglingChannel(null);
    }
  };

  if (prefsFailed || linksFailed) {
    return (
      <SettingsPage>
        <PreferencesError
          onRetry={() => {
            if (prefsFailed) void fetchPrefs();
            if (linksFailed) void refetchLinks();
          }}
        />
      </SettingsPage>
    );
  }

  const channelSwitch = (channel: ChannelPlatform, description: string) => (
    <ChannelRow key={channel} channel={channel} description={description}>
      <Switch
        size="sm"
        isSelected={!!channelPrefs?.[channel]}
        isDisabled={togglingChannel === channel}
        onValueChange={(enabled) => handleToggle(channel, enabled)}
        aria-label={`Enable ${NOTIFICATION_CHANNEL_LABELS[channel]} notifications`}
      />
    </ChannelRow>
  );

  return (
    <SettingsPage>
      <QuietHoursSettings />
      {channelPrefs && links && (
        <SettingsSection
          title="Channels"
          description="Where GAIA can reach you."
        >
          {channelSwitch("email", EMAIL_CHANNEL_DESCRIPTION)}
          {linkedOrder.map((platform) => {
            const user = linkedAs(platform);
            return channelSwitch(
              platform,
              user ? `Connected as ${user}` : "Connected",
            );
          })}
          {unlinkedPlatforms.map((platform) => (
            <ChannelRow
              key={platform}
              channel={platform}
              description="Not connected"
            >
              <div className="flex items-center gap-3">
                {isLockedBehindPro(platform) && (
                  <Chip size="sm" variant="flat" color="warning">
                    Pro
                  </Chip>
                )}
                <Button
                  size="sm"
                  variant="flat"
                  color="primary"
                  aria-label={`Connect ${NOTIFICATION_CHANNEL_LABELS[platform]}`}
                  isLoading={connectingPlatform === platform}
                  isDisabled={linksLoading || connectingPlatform != null}
                  onPress={() => connect(platform)}
                >
                  Connect
                </Button>
              </div>
            </ChannelRow>
          ))}
          {linkedOrder.length > 1 && (
            <SettingsRow
              label="Text me first on"
              description="When you haven't chatted lately, GAIA starts here."
            >
              <Select
                size="sm"
                className="w-36"
                aria-label="Text me first on"
                disallowEmptySelection
                selectedKeys={[linkedOrder[0]]}
                isDisabled={saving}
                onSelectionChange={(keys) => {
                  const [next] = Array.from(keys, String);
                  if (next && isBotPlatform(next)) void putFirst(next);
                }}
              >
                {linkedOrder.map((platform) => (
                  <SelectItem key={platform}>
                    {NOTIFICATION_CHANNEL_LABELS[platform]}
                  </SelectItem>
                ))}
              </Select>
            </SettingsRow>
          )}
        </SettingsSection>
      )}
      <PhoneLinkModal {...phoneLinkModal} />
    </SettingsPage>
  );
}

interface ChannelRowProps {
  channel: ChannelPlatform;
  description: string;
  children: ReactNode;
}

function ChannelRow({ channel, description, children }: ChannelRowProps) {
  const label = NOTIFICATION_CHANNEL_LABELS[channel];
  return (
    <SettingsRow
      label={label}
      description={description}
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
      {children}
    </SettingsRow>
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
