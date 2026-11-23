"use client";

import {
  Chip,
  Dropdown,
  DropdownItem,
  DropdownMenu,
  DropdownPopover,
  Label,
} from "@heroui/react";
import { MoreHorizontalIcon, Unlink04Icon } from "@icons";
import Image from "next/image";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { LoadError } from "@/components/shared/LoadError";
import { PhoneLinkModal } from "@/components/shared/PhoneLinkModal";
import {
  BOT_PLATFORM_ICONS,
  BOT_PLATFORM_LABELS,
  BOT_PLATFORMS,
  type BotPlatform,
} from "@/config/botPlatforms";
import { OpenPlatformChatButton } from "@/features/settings/components/OpenPlatformChatButton";
import { SettingsPage } from "@/features/settings/components/ui/SettingsPage";
import { SettingsRow } from "@/features/settings/components/ui/SettingsRow";
import { SettingsSection } from "@/features/settings/components/ui/SettingsSection";
import { LINKED_PLATFORM_DETAILS } from "@/features/settings/constants";
import { usePlatformLinks } from "@/features/settings/hooks/usePlatformLinks";
import { connectedAsLabel } from "@/features/settings/utils/platformLinkLabels";

export default function LinkedAccountsSettings() {
  const {
    isLoading,
    loadFailed,
    refetch,
    isLinked,
    linkedAs,
    isLockedBehindPro,
    connectingPlatform,
    connect,
    disconnect,
    phoneLinkModal,
  } = usePlatformLinks();

  if (loadFailed) {
    return (
      <SettingsPage>
        <LoadError
          title="Couldn't load your linked accounts"
          description="Your accounts are still linked. This page just couldn't reach them."
          onRetry={refetch}
        />
      </SettingsPage>
    );
  }

  return (
    <SettingsPage>
      <SettingsSection description="Connect your messaging platforms to use GAIA from anywhere.">
        {BOT_PLATFORMS.map((platform) => {
          const details = LINKED_PLATFORM_DETAILS[platform];
          const name = BOT_PLATFORM_LABELS[platform];
          const isConnected = isLinked(platform);

          return (
            <SettingsRow
              key={platform}
              label={name}
              description={
                isConnected
                  ? linkedDescription(platform, linkedAs(platform))
                  : details.description
              }
              icon={
                <Image
                  src={BOT_PLATFORM_ICONS[platform]}
                  alt={name}
                  width={36}
                  height={36}
                  className="rounded-xl"
                />
              }
            >
              {isConnected ? (
                <div className="flex items-center gap-2">
                  {details.chat && (
                    <OpenPlatformChatButton platform={platform} />
                  )}
                  <Dropdown>
                    <GaiaButton
                      isIconOnly
                      size="sm"
                      variant="ghost"
                      aria-label={`More for ${name}`}
                      isDisabled={isLoading || connectingPlatform != null}
                    >
                      <MoreHorizontalIcon className="size-4 text-zinc-400" />
                    </GaiaButton>
                    <DropdownPopover placement="bottom end">
                      <DropdownMenu
                        aria-label={`${name} actions`}
                        onAction={() => void disconnect(platform)}
                      >
                        <DropdownItem
                          id="disconnect"
                          textValue="Disconnect"
                          variant="danger"
                        >
                          <Unlink04Icon className="size-4" />
                          <Label>Disconnect</Label>
                        </DropdownItem>
                      </DropdownMenu>
                    </DropdownPopover>
                  </Dropdown>
                </div>
              ) : (
                <div className="flex items-center gap-3">
                  {isLockedBehindPro(platform) && (
                    <Chip size="sm" variant="soft" color="warning">
                      <Chip.Label>Pro</Chip.Label>
                    </Chip>
                  )}
                  <GaiaButton
                    variant="accent-soft"
                    size="sm"
                    aria-label={`Connect ${name}`}
                    onPress={() => connect(platform)}
                    isPending={connectingPlatform === platform}
                    isDisabled={isLoading || connectingPlatform != null}
                    className="text-xs"
                  >
                    Connect
                  </GaiaButton>
                </div>
              )}
            </SettingsRow>
          );
        })}
      </SettingsSection>

      <SettingsSection title="How it works">
        <div className="px-4 py-3.5">
          <ul className="list-disc space-y-1.5 pl-4 text-sm text-zinc-400 marker:text-zinc-600">
            <li>Connect your account using the button above</li>
            <li>
              Use{" "}
              <code className="rounded bg-zinc-800 px-1 py-0.5 text-xs text-zinc-300">
                /gaia
              </code>{" "}
              in Discord or Slack, or just message the Telegram, WhatsApp, or
              iMessage bot
            </li>
            <li>All conversations sync with your GAIA account</li>
            <li>Disconnect anytime from this page</li>
          </ul>
        </div>
      </SettingsSection>

      <PhoneLinkModal {...phoneLinkModal} />
    </SettingsPage>
  );
}

/** Who the link is, and for the apps with no chat to open, how to reach GAIA there. */
function linkedDescription(
  platform: BotPlatform,
  user: string | undefined,
): string {
  const details = LINKED_PLATFORM_DETAILS[platform];
  return [
    connectedAsLabel(user),
    details.chat ? null : details.connectedDescription,
  ]
    .filter(Boolean)
    .join(" · ");
}
