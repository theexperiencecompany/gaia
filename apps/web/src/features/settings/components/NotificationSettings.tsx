"use client";

import { EMAIL_CHANNEL_DESCRIPTION } from "@gaia/shared";
import type { ChannelPlatform } from "@gaia/shared/types";
import { ListBox, Select, Switch } from "@heroui/react";
import Image from "next/image";
import type { ReactNode } from "react";
import { inputVariants } from "@/components/shared/controlVariants";
import { GaiaListBoxItem } from "@/components/shared/GaiaListBoxItem";
import { GaiaSelectValue } from "@/components/shared/GaiaSelectValue";
import { LinkButton } from "@/components/shared/LinkButton";
import { LoadError } from "@/components/shared/LoadError";
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
import { LINKED_ACCOUNTS_SETTINGS_PATH } from "@/features/settings/constants";
import { useChannelPreferences } from "@/features/settings/hooks/useChannelPreferences";
import { useChatChannelSettings } from "@/features/settings/hooks/useChatChannelSettings";
import { usePlatformLinks } from "@/features/settings/hooks/usePlatformLinks";
import { connectedAsLabel } from "@/features/settings/utils/platformLinkLabels";

export default function NotificationSettings() {
  const channels = useChannelPreferences();
  const {
    links,
    loadFailed: linksFailed,
    refetch: refetchLinks,
    isLinked,
    linkedAs,
  } = usePlatformLinks();
  const linkedPlatforms = NOTIFICATION_PLATFORMS.filter(isLinked);
  const unlinkedPlatforms = NOTIFICATION_PLATFORMS.filter(
    (platform) => !isLinked(platform),
  );
  const chatChannel = useChatChannelSettings(linkedPlatforms);
  const { linkedOrder, saving, putFirst } = chatChannel;
  const channelPrefs = channels.preferences;

  if (channels.loadFailed || linksFailed || chatChannel.loadFailed) {
    return (
      <SettingsPage>
        <LoadError
          title="Couldn't load your notification settings"
          description="Your channels are unchanged. This page just couldn't reach them."
          onRetry={() => {
            if (channels.loadFailed) channels.refetch();
            if (linksFailed) refetchLinks();
            if (chatChannel.loadFailed) chatChannel.refetch();
          }}
        />
      </SettingsPage>
    );
  }

  const channelSwitch = (channel: ChannelPlatform) => (
    <Switch
      size="sm"
      isSelected={!!channelPrefs?.[channel]}
      onChange={(enabled) => channels.toggle(channel, enabled)}
      aria-label={`Enable ${NOTIFICATION_CHANNEL_LABELS[channel]} notifications`}
    >
      <Switch.Content>
        <Switch.Control>
          <Switch.Thumb />
        </Switch.Control>
      </Switch.Content>
    </Switch>
  );

  return (
    <SettingsPage>
      <QuietHoursSettings />
      {channelPrefs && links && linkedOrder && (
        <SettingsSection
          title="Channels"
          description="Where GAIA reaches you. Chat apps are linked in Linked Accounts."
        >
          <ChannelRow channel="email" description={EMAIL_CHANNEL_DESCRIPTION}>
            {channelSwitch("email")}
          </ChannelRow>
          {linkedOrder.map((platform) => (
            <ChannelRow
              key={platform}
              channel={platform}
              description={connectedAsLabel(linkedAs(platform))}
            >
              {channelSwitch(platform)}
            </ChannelRow>
          ))}
          {unlinkedPlatforms.map((platform) => (
            <ChannelRow
              key={platform}
              channel={platform}
              description="Not linked"
            >
              <LinkButton
                href={LINKED_ACCOUNTS_SETTINGS_PATH}
                size="sm"
                variant="default-soft"
                aria-label={`Link ${NOTIFICATION_CHANNEL_LABELS[platform]} in Linked Accounts`}
                className="text-xs"
              >
                Link
              </LinkButton>
            </ChannelRow>
          ))}
          {linkedOrder.length > 1 && (
            <SettingsRow
              label="Text me first on"
              description="When you haven't chatted lately, GAIA starts here."
            >
              <Select
                className={inputVariants({ size: "sm", className: "w-36" })}
                aria-label="Text me first on"
                value={linkedOrder[0]}
                isDisabled={saving}
                onChange={(key) => {
                  const next = key == null ? null : String(key);
                  if (next && isBotPlatform(next)) void putFirst(next);
                }}
              >
                <Select.Trigger>
                  <GaiaSelectValue />
                  <Select.Indicator />
                </Select.Trigger>
                <Select.Popover>
                  <ListBox>
                    {linkedOrder.map((platform) => (
                      <GaiaListBoxItem
                        key={platform}
                        id={platform}
                        textValue={NOTIFICATION_CHANNEL_LABELS[platform]}
                      />
                    ))}
                  </ListBox>
                </Select.Popover>
              </Select>
            </SettingsRow>
          )}
          <SettingsRow
            label="Linked accounts"
            description="Connect, disconnect or open a chat app."
          >
            <LinkButton
              href={LINKED_ACCOUNTS_SETTINGS_PATH}
              size="sm"
              variant="default-soft"
              className="text-xs"
            >
              Manage
            </LinkButton>
          </SettingsRow>
        </SettingsSection>
      )}
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
