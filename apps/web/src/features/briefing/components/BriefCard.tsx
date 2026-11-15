"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { NewsIcon } from "@icons";
import { format, isToday, isYesterday, parseISO } from "date-fns";
import Image from "next/image";

import { cn } from "@/lib/utils";

/** What a folded brief shows before it is opened. */
export interface FoldedBriefSummary {
  headline: string;
  /** ISO day of the brief (YYYY-MM-DD). */
  date?: string;
  kind?: "daily" | "weekly";
  lede?: string;
  imageUrl?: string | null;
  /** Share of the edition's height where its letter folds. */
  editionFold?: number | null;
  /** The paper's box on its desk, [left, top, right, bottom] shares of the edition. */
  editionPaper?: number[] | null;
  editionName?: string | null;
  stampCityName?: string | null;
  needsYouCount?: number | null;
}

/** Below this, a waiting count is the ordinary day and not worth a line. */
const NOTABLE_NEEDS_YOU = 3;

const TONE_CLASSES = {
  raised: "bg-zinc-800",
  inset: "bg-zinc-900",
  bare: "bg-transparent",
} as const;

const KIND_LABELS = { daily: "Daily", weekly: "Weekly" } as const;

export type BriefCardTone = keyof typeof TONE_CLASSES;

interface BriefCardProps {
  brief: FoldedBriefSummary;
  /** "raised" on the page background, "inset" inside a zinc-800 card, "bare" where the page itself groups the cards. */
  tone?: BriefCardTone;
  isBusy?: boolean;
  onPress: () => void;
  onWarm: () => void;
}

const TODAY_LABEL = "Today";

function dateLabel(brief: FoldedBriefSummary): string | null {
  if (!brief.date) return null;
  const date = parseISO(brief.date);
  const day = format(date, "EEE d MMM");
  if (brief.kind === "weekly") return `Week to ${day}`;
  if (isToday(date)) return TODAY_LABEL;
  if (isYesterday(date)) return "Yesterday";
  return day;
}

function editionLabel(brief: FoldedBriefSummary): string | null {
  return (
    [brief.editionName, brief.stampCityName].filter(Boolean).join(", ") || null
  );
}

/** The edition's masthead. */
function Preview({ imageUrl }: { imageUrl?: string | null }) {
  return (
    <div className="relative aspect-[3/2] overflow-hidden rounded-[10px] bg-zinc-700/40 transition-[filter] duration-200 ease-out group-data-[hover=true]:brightness-110">
      {imageUrl ? (
        <Image
          src={imageUrl}
          alt=""
          fill
          sizes="(max-width: 640px) 50vw, 240px"
          className="object-cover object-top"
        />
      ) : (
        <span className="absolute inset-0 flex items-center justify-center">
          <NewsIcon className="size-6 text-zinc-500" />
        </span>
      )}
    </div>
  );
}

/** A brief folded to a letter: its edition's masthead, then the date, what it said, and the edition. */
export function BriefCard({
  brief,
  tone = "raised",
  isBusy = false,
  onPress,
  onWarm,
}: BriefCardProps) {
  const date = dateLabel(brief);
  const edition = editionLabel(brief);
  const needsYou = brief.needsYouCount ?? 0;

  return (
    <Button
      disableRipple
      onPress={onPress}
      onPointerEnter={onWarm}
      onPointerDown={onWarm}
      onFocus={onWarm}
      aria-label={`Open brief: ${brief.headline}`}
      aria-busy={isBusy}
      className={cn(
        "group relative h-full w-full min-w-0 flex-col items-stretch justify-start gap-0 rounded-2xl p-1.5 text-left whitespace-normal transition-[scale] duration-200 ease-out after:pointer-events-none after:absolute after:inset-0 after:rounded-2xl after:bg-white/0 after:transition-colors after:duration-200 after:ease-out data-[hover=true]:opacity-100 data-[hover=true]:after:bg-white/5 data-[pressed=true]:scale-[0.97]",
        TONE_CLASSES[tone],
      )}
    >
      <Preview imageUrl={brief.imageUrl} />
      <span className="flex min-w-0 flex-1 flex-col gap-1 px-1.5 pt-2 pb-1">
        {(date || needsYou >= NOTABLE_NEEDS_YOU) && (
          <span className="flex items-baseline justify-between gap-2 text-xs text-zinc-500">
            <span
              className={cn(
                "truncate",
                date === TODAY_LABEL && "font-medium text-primary",
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
        )}
        <span className="line-clamp-2 text-sm font-medium leading-snug text-balance text-zinc-100">
          {brief.headline}
        </span>
        {brief.lede && (
          <span className="line-clamp-2 text-xs leading-relaxed text-pretty text-zinc-400">
            {brief.lede}
          </span>
        )}
        {(brief.kind || edition) && (
          <span className="mt-auto flex min-w-0 items-center gap-1.5 pt-1">
            {brief.kind && (
              <Chip
                size="sm"
                variant="flat"
                color={brief.kind === "weekly" ? "primary" : "default"}
                className="shrink-0"
              >
                {KIND_LABELS[brief.kind]}
              </Chip>
            )}
            {edition && (
              <span className="truncate text-xs text-zinc-500">{edition}</span>
            )}
          </span>
        )}
      </span>
    </Button>
  );
}
