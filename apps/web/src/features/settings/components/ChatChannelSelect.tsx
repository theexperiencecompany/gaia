"use client";

import { ListBox, Select } from "@heroui/react";
import { inputVariants } from "@/components/shared/controlVariants";
import { GaiaListBoxItem } from "@/components/shared/GaiaListBoxItem";
import { GaiaSelectValue } from "@/components/shared/GaiaSelectValue";
import { isBotPlatform } from "@/config/botPlatforms";
import {
  NOTIFICATION_CHANNEL_LABELS,
  type NotificationPlatform,
} from "@/features/notification/constants";

/** The setting's name, said by its row and to a screen reader. */
export const CHAT_CHANNEL_SELECT_LABEL = "Text me first on";

interface ChatChannelSelectProps {
  /** The linked chat apps, the one GAIA texts first leading. */
  linkedOrder: NotificationPlatform[];
  saving: boolean;
  putFirst: (platform: NotificationPlatform) => void;
}

/** Picks the one chat app GAIA texts when the user has not chatted anywhere lately. */
export function ChatChannelSelect({
  linkedOrder,
  saving,
  putFirst,
}: ChatChannelSelectProps) {
  return (
    <Select
      className={inputVariants({ size: "sm", className: "w-36" })}
      aria-label={CHAT_CHANNEL_SELECT_LABEL}
      value={linkedOrder[0]}
      isDisabled={saving}
      onChange={(key) => {
        const next = key == null ? null : String(key);
        if (next && isBotPlatform(next)) putFirst(next);
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
  );
}
