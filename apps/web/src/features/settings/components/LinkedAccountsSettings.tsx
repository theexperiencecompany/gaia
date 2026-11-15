"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import Image from "next/image";
import { PhoneLinkModal } from "@/components/shared/PhoneLinkModal";
import {
  BOT_PLATFORM_ICONS,
  BOT_PLATFORM_LABELS,
  BOT_PLATFORMS,
} from "@/config/botPlatforms";
import { OpenPlatformChatButton } from "@/features/settings/components/OpenPlatformChatButton";
import { SettingsPage } from "@/features/settings/components/ui/SettingsPage";
import { SettingsRow } from "@/features/settings/components/ui/SettingsRow";
import { SettingsSection } from "@/features/settings/components/ui/SettingsSection";
import { LINKED_PLATFORM_DETAILS } from "@/features/settings/constants";
import { usePlatformLinks } from "@/features/settings/hooks/usePlatformLinks";
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
          const userLabel = linkedAs(platform);

          return (
            <SettingsRow
              key={platform}
              label={name}
              description={
                isConnected
                  ? userLabel
                    ? `${details.connectedDescription} · ${userLabel}`
                    : details.connectedDescription
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
              <div className="flex items-center gap-3">
                {isLockedBehindPro(platform) && (
                  <Chip size="sm" variant="flat" color="warning">
                    Pro
                  </Chip>
                )}
                {isConnected && (
                  <span className="flex items-center gap-1 rounded-full bg-emerald-500/15 px-2 py-0.5 text-xs font-medium text-emerald-400">
                    <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
                    Connected
                  </span>
                )}
                {isConnected && details.chat && (
                  <OpenPlatformChatButton platform={platform} />
                )}
                <Button
                  variant="flat"
                  color={isConnected ? "danger" : "primary"}
                  size="sm"
                  onPress={() =>
                    isConnected ? disconnect(platform) : connect(platform)
                  }
                  isLoading={connectingPlatform === platform}
                  isDisabled={isLoading || connectingPlatform != null}
                  className="text-xs"
                >
                  {isConnected ? "Disconnect" : "Connect"}
                </Button>
              </div>
            </SettingsRow>
          );
        })}
      </SettingsSection>

      <SettingsSection title="How it works">
        <div className="px-4 py-3.5">
          <ul className="space-y-1.5 text-sm text-zinc-400">
            <li className="flex items-start gap-2">
              <span className="mt-0.5 text-zinc-600">•</span>
              Connect your account using the button above
            </li>
            <li className="flex items-start gap-2">
              <span className="mt-0.5 text-zinc-600">•</span>
              Use{" "}
              <code className="rounded bg-zinc-800 px-1 py-0.5 text-xs text-zinc-300">
                /gaia
              </code>{" "}
              in Discord or Slack, or just message the Telegram, WhatsApp, or
              iMessage bot
            </li>
            <li className="flex items-start gap-2">
              <span className="mt-0.5 text-zinc-600">•</span>
              All conversations sync with your GAIA account
            </li>
            <li className="flex items-start gap-2">
              <span className="mt-0.5 text-zinc-600">•</span>
              Disconnect anytime from this page
            </li>
          </ul>
        </div>
      </SettingsSection>

      <PhoneLinkModal {...phoneLinkModal} />
    </SettingsPage>
  );
}
