"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import {
  Dropdown,
  DropdownItem,
  DropdownMenu,
  DropdownTrigger,
} from "@heroui/dropdown";
import { MoreHorizontalIcon, Unlink04Icon } from "@icons";
import Image from "next/image";
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
import { toast } from "@/lib/toast";

const notifyLoadError = () => toast.error("Failed to load connected accounts");

export default function LinkedAccountsSettings() {
  const {
    isLoading,
    isLinked,
    linkedAs,
    isLockedBehindPro,
    connectingPlatform,
    connect,
    disconnect,
    phoneLinkModal,
  } = usePlatformLinks({ onLoadError: notifyLoadError });

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
                  <Dropdown placement="bottom-end">
                    <DropdownTrigger>
                      <Button
                        isIconOnly
                        size="sm"
                        variant="light"
                        aria-label={`More for ${name}`}
                        isDisabled={isLoading || connectingPlatform != null}
                      >
                        <MoreHorizontalIcon className="size-4 text-zinc-400" />
                      </Button>
                    </DropdownTrigger>
                    <DropdownMenu
                      aria-label={`${name} actions`}
                      onAction={() => void disconnect(platform)}
                    >
                      <DropdownItem
                        key="disconnect"
                        color="danger"
                        className="text-danger"
                        startContent={<Unlink04Icon className="size-4" />}
                      >
                        Disconnect
                      </DropdownItem>
                    </DropdownMenu>
                  </Dropdown>
                </div>
              ) : (
                <div className="flex items-center gap-3">
                  {isLockedBehindPro(platform) && (
                    <Chip size="sm" variant="flat" color="warning">
                      Pro
                    </Chip>
                  )}
                  <Button
                    variant="flat"
                    color="primary"
                    size="sm"
                    aria-label={`Connect ${name}`}
                    onPress={() => connect(platform)}
                    isLoading={connectingPlatform === platform}
                    isDisabled={isLoading || connectingPlatform != null}
                    className="text-xs"
                  >
                    Connect
                  </Button>
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
