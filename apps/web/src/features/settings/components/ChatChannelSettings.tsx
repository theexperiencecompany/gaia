"use client";

import { Button } from "@heroui/button";
import { ArrowDown01Icon, ArrowUp01Icon } from "@icons";
import Image from "next/image";
import Link from "next/link";
import {
  NOTIFICATION_PLATFORM_ICONS,
  NOTIFICATION_PLATFORM_LABELS,
  type NotificationPlatform,
} from "@/features/notification/constants";
import { SettingsRow } from "@/features/settings/components/ui/SettingsRow";
import { SettingsSection } from "@/features/settings/components/ui/SettingsSection";
import { useChatChannelSettings } from "@/features/settings/hooks/useChatChannelSettings";

interface ChatChannelSettingsProps {
  /** The bot platforms this user has actually linked, in any order. */
  linkedPlatforms: NotificationPlatform[];
}

/**
 * "Where GAIA texts you" — the priority order of the user's linked platforms.
 */
export function ChatChannelSettings({
  linkedPlatforms,
}: ChatChannelSettingsProps) {
  const { linkedOrder, saving, move } = useChatChannelSettings(linkedPlatforms);

  return (
    <SettingsSection
      title="Where GAIA texts you"
      description={
        linkedOrder.length < 2
          ? "Link another platform to choose where GAIA texts you first."
          : "GAIA texts you on the chat app you've used in the last few hours, or in this order if you haven't. While you're active in the GAIA app, it messages you there instead."
      }
    >
      {linkedOrder.map((platform, index) => {
        const label = NOTIFICATION_PLATFORM_LABELS[platform];
        return (
          <SettingsRow
            key={platform}
            label={label}
            description={index === 0 ? "First in line" : undefined}
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
            <div className="flex items-center gap-1">
              <Button
                isIconOnly
                size="sm"
                variant="light"
                radius="lg"
                aria-label={`Move ${label} up`}
                isDisabled={index === 0 || saving}
                onPress={() => move(index, "up")}
              >
                <ArrowUp01Icon className="size-4" />
              </Button>
              <Button
                isIconOnly
                size="sm"
                variant="light"
                radius="lg"
                aria-label={`Move ${label} down`}
                isDisabled={index === linkedOrder.length - 1 || saving}
                onPress={() => move(index, "down")}
              >
                <ArrowDown01Icon className="size-4" />
              </Button>
            </div>
          </SettingsRow>
        );
      })}
      {linkedOrder.length < 2 && (
        <SettingsRow label="Linked Accounts">
          <Link
            href="/settings/linked-accounts"
            className="text-sm text-primary"
          >
            Connect a platform
          </Link>
        </SettingsRow>
      )}
    </SettingsSection>
  );
}
