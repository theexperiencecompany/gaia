"use client";

import { WebhookIcon } from "@icons";

import { AppIcon } from "./AppIcon";
import { type ChipTone, MetaChip } from "./MetaChip";
import { WHEN_ICONS } from "./taskIcons";
import type { TaskWhen } from "./taskModel";
import { WatchIcon } from "./WatchIcon";

/**
 * When a task is due or runs, always as one chip, on Tasks and on Explore alike.
 * Colour is kept for the two that need you today; an event trigger leads with the
 * app that fires it.
 */
export function WhenChip({ when }: { when: TaskWhen }) {
  if (!when.label) return null;
  // A watch shows what it reads and the latest reading: the one number you'd open it for.
  if (when.watch)
    return (
      <MetaChip icon={<WatchIcon source={when.watch.source} size={14} />}>
        {when.watch.reading?.value ?? when.label}
      </MetaChip>
    );
  const Icon = WHEN_ICONS[when.kind];
  const tone: ChipTone = when.overdue
    ? "danger"
    : when.isToday
      ? "success"
      : when.kind === "schedule"
        ? "info"
        : "default";

  return (
    <MetaChip
      tone={tone}
      icon={
        when.app ? (
          <AppIcon id={when.app} size={14} />
        ) : when.webhook ? (
          <WebhookIcon className="size-3.5" />
        ) : (
          <Icon className="size-3.5" />
        )
      }
    >
      {when.overdue ? `Overdue, ${when.label}` : when.label}
    </MetaChip>
  );
}
