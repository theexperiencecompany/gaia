"use client";

import { Chip } from "@heroui/react";
import { NewsIcon } from "@icons";
import { formatDate, formatDay, TODAY } from "@shared/utils";
import { parseISO } from "date-fns";
import Image from "next/image";
import { useId, useState } from "react";

import {
  NESTED_TONE,
  type SurfaceTone,
  surfaceVariants,
} from "@/components/shared/surfaceVariants";
import { cn } from "@/lib/utils";

import type { BriefTriggerState } from "../hooks/useOpenBrief";
import type { FoldedBriefSummary } from "../utils/briefCard";
import { BriefTrigger } from "./BriefTrigger";

/** Below this, a waiting count is the ordinary day and not worth a line. */
const NOTABLE_NEEDS_YOU = 3;

const KIND_LABELS = { daily: "Daily", weekly: "Weekly" } as const;

interface FoldedBriefCardProps {
  brief: FoldedBriefSummary;
  /** "raised" on the page background, "inset" inside a zinc-800 card. */
  tone?: SurfaceTone;
  /** Off where the card is filed under its title alone (the archive). */
  showsWaiting?: boolean;
  trigger: BriefTriggerState;
}

function dateLabel(brief: FoldedBriefSummary): string {
  const date = parseISO(brief.date);
  if (brief.kind === "weekly") return `Week to ${formatDate(date, "day")}`;
  return formatDay(date, "day");
}

function editionLabel(brief: FoldedBriefSummary): string | null {
  return (
    [brief.editionName, brief.stampCityName].filter(Boolean).join(", ") || null
  );
}

/** The edition's masthead, on a well one step off the card. */
function Preview({
  imageUrl,
  tone,
}: {
  imageUrl?: string | null;
  tone: SurfaceTone;
}) {
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  // The preview sits one step off the card it is in, so the edition reads as its own sheet.
  return (
    <div
      className={surfaceVariants({
        tone: NESTED_TONE[tone],
        className: "rounded-[10px] p-1.5",
      })}
    >
      <div className="relative aspect-[3/2] overflow-hidden rounded-[4px] transition-[filter] duration-200 ease-out group-hover:brightness-110">
        {imageUrl && failedUrl !== imageUrl ? (
          // A signed, per-reader URL: served as is, never through the shared image optimizer.
          <Image
            src={imageUrl}
            alt=""
            fill
            unoptimized
            sizes="(max-width: 640px) 50vw, 240px"
            className="object-cover object-top"
            onError={() => setFailedUrl(imageUrl)}
          />
        ) : (
          <span className="absolute inset-0 flex items-center justify-center">
            <NewsIcon className="size-6 text-zinc-500" />
          </span>
        )}
      </div>
    </div>
  );
}

/** A brief folded to a letter: its edition's masthead, then the date, what it said, and the edition. */
export function FoldedBriefCard({
  brief,
  tone = "raised",
  showsWaiting = true,
  trigger,
}: FoldedBriefCardProps) {
  const date = dateLabel(brief);
  const edition = editionLabel(brief);
  const needsYou = showsWaiting ? brief.needsYouCount : 0;
  // The name stays the headline; the date and edition are read after it as its description.
  const id = useId();

  return (
    <BriefTrigger
      trigger={trigger}
      onPress={() => trigger.open()}
      aria-label={`Open brief: ${brief.headline}`}
      aria-describedby={`${id}-meta ${id}-foot`}
      className={cn(
        "group relative flex h-full w-full min-w-0 flex-col items-stretch justify-start gap-0 rounded-2xl p-1.5 text-left whitespace-normal transition-[scale] duration-200 ease-out after:pointer-events-none after:absolute after:inset-0 after:rounded-2xl after:bg-white/0 after:transition-colors after:duration-200 after:ease-out hover:after:bg-white/5 active:scale-[0.97]",
        surfaceVariants({ tone }),
      )}
    >
      <Preview imageUrl={brief.imageUrl} tone={tone} />
      <span className="flex min-w-0 flex-1 flex-col gap-1 px-1.5 pt-2 pb-1">
        <span
          id={`${id}-meta`}
          className="flex items-baseline justify-between gap-2 text-xs text-zinc-500"
        >
          <span
            className={cn(
              "truncate",
              date === TODAY && "font-medium text-accent",
            )}
          >
            {date}
          </span>
          {needsYou >= NOTABLE_NEEDS_YOU && (
            <span className="shrink-0 text-amber-300/90 tabular-nums">
              {needsYou} waiting
            </span>
          )}
        </span>
        <span className="line-clamp-2 text-sm font-medium leading-snug text-balance text-zinc-100">
          {brief.headline}
        </span>
        <span
          id={`${id}-foot`}
          className="mt-auto flex min-w-0 items-center gap-1.5 pt-1"
        >
          <Chip
            size="sm"
            variant="soft"
            color={brief.kind === "weekly" ? "accent" : "default"}
            className="shrink-0"
          >
            <Chip.Label>{KIND_LABELS[brief.kind]}</Chip.Label>
          </Chip>
          {edition && (
            <span className="truncate text-xs text-zinc-500">{edition}</span>
          )}
        </span>
      </span>
    </BriefTrigger>
  );
}
