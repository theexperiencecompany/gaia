"use client";

import Image from "next/image";
import type { CSSProperties } from "react";

import { LinkButton } from "@/components/shared/LinkButton";
import {
  NOTIFICATION_CHANNEL_ICONS,
  NOTIFICATION_CHANNEL_LABELS,
  type NotificationPlatform,
} from "@/features/notification/constants";
import { SettingsRow } from "@/features/settings/components/ui/SettingsRow";
import { LINKED_ACCOUNTS_SETTINGS_PATH } from "@/features/settings/constants";

const ICON_SIZE_PX = 28;
const SWAY_DEG = 8;
const STAGGER_SECONDS = 0.45;

/** The chat apps that are not linked yet, as one row that leads to Linked Accounts. */
export function UnlinkedPlatformsRow({
  platforms,
}: {
  platforms: readonly NotificationPlatform[];
}) {
  if (platforms.length === 0) return null;

  return (
    <SettingsRow
      label="Not linked yet"
      description={platforms
        .map((platform) => NOTIFICATION_CHANNEL_LABELS[platform])
        .join(", ")}
      icon={
        <div aria-hidden className="flex items-center -space-x-2">
          {platforms.map((platform, index) => (
            <span
              key={platform}
              className="block rounded-lg motion-safe:animate-icon-sway"
              style={
                {
                  "--sway-deg": `${index % 2 === 0 ? SWAY_DEG : -SWAY_DEG}deg`,
                  animationDelay: `${index * STAGGER_SECONDS}s`,
                } as CSSProperties
              }
            >
              <Image
                src={NOTIFICATION_CHANNEL_ICONS[platform]}
                alt=""
                width={ICON_SIZE_PX}
                height={ICON_SIZE_PX}
                className="rounded-lg ring-2 ring-zinc-900"
              />
            </span>
          ))}
        </div>
      }
    >
      <LinkButton
        href={LINKED_ACCOUNTS_SETTINGS_PATH}
        size="sm"
        variant="default-soft"
        className="text-xs"
      >
        Manage linked accounts
      </LinkButton>
    </SettingsRow>
  );
}
