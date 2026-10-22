"use client";

import { Button } from "@heroui/button";
import { NewsIcon } from "@icons";
import { format, parseISO } from "date-fns";
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
  editionName?: string | null;
  stampCityName?: string | null;
  needsYouCount?: number | null;
}

/** Below this, a waiting count is the ordinary day and not worth a line. */
const NOTABLE_NEEDS_YOU = 3;

const TONE_CLASSES = {
  raised: "bg-zinc-800 data-[hover=true]:bg-zinc-700/80",
  inset: "bg-zinc-900 data-[hover=true]:bg-zinc-950/80",
} as const;

export type BriefCardTone = keyof typeof TONE_CLASSES;

interface BriefCardProps {
  brief: FoldedBriefSummary;
  /** "feature" lays the weekly recap out wide, preview beside its words. */
  variant?: "card" | "feature";
  /** "raised" on the page background, "inset" inside a zinc-800 card. */
  tone?: BriefCardTone;
  isBusy?: boolean;
  onPress: () => void;
  onWarm: () => void;
}

function dateLabel(brief: FoldedBriefSummary): string | null {
  if (!brief.date) return null;
  const day = format(parseISO(brief.date), "EEE d MMM");
  return brief.kind === "weekly" ? `Week to ${day}` : day;
}

function editionLabel(brief: FoldedBriefSummary): string | null {
  if (brief.kind === "weekly") return "Weekly recap";
  return (
    [brief.editionName, brief.stampCityName].filter(Boolean).join(", ") || null
  );
}

/** The edition's masthead, with a hairline crease where the letter was folded. */
function Preview({
  imageUrl,
  isFeature,
}: {
  imageUrl?: string | null;
  isFeature: boolean;
}) {
  return (
    <div
      className={cn(
        "relative aspect-[3/2] overflow-hidden rounded-[10px] bg-zinc-700/40",
        isFeature && "sm:w-60 sm:shrink-0",
      )}
    >
      {imageUrl ? (
        <Image
          src={imageUrl}
          alt=""
          fill
          sizes={
            isFeature
              ? "(max-width: 640px) 50vw, 300px"
              : "(max-width: 640px) 50vw, 240px"
          }
          className="object-cover object-top"
        />
      ) : (
        <span className="absolute inset-0 flex items-center justify-center">
          <NewsIcon className="size-6 text-zinc-500" />
        </span>
      )}
      <span
        aria-hidden
        className="absolute inset-x-0 top-2/3 h-px bg-black/20"
      />
      <span
        aria-hidden
        className="absolute inset-x-0 top-2/3 mt-px h-px bg-white/25"
      />
      <span
        aria-hidden
        className="pointer-events-none absolute inset-0 rounded-[10px] ring-1 ring-white/10 ring-inset"
      />
    </div>
  );
}

/** A brief folded to a letter: its edition's masthead, then the date, headline and edition that tell it apart. */
export function BriefCard({
  brief,
  variant = "card",
  tone = "raised",
  isBusy = false,
  onPress,
  onWarm,
}: BriefCardProps) {
  const isFeature = variant === "feature";
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
        "h-full w-full min-w-0 items-stretch justify-start gap-0 rounded-2xl p-1.5 text-left whitespace-normal transition-[background-color,scale] data-[pressed=true]:scale-[0.97]",
        isFeature ? "flex-col sm:flex-row" : "flex-col",
        TONE_CLASSES[tone],
      )}
    >
      <Preview imageUrl={brief.imageUrl} isFeature={isFeature} />
      <span
        className={cn(
          "flex min-w-0 flex-1 flex-col gap-1 px-1.5 pt-2 pb-1",
          isFeature && "sm:justify-center sm:px-4 sm:py-3",
        )}
      >
        {(date || needsYou >= NOTABLE_NEEDS_YOU) && (
          <span className="flex items-baseline justify-between gap-2 text-xs text-zinc-500">
            <span className="truncate">{date}</span>
            {needsYou >= NOTABLE_NEEDS_YOU && (
              <span className="shrink-0 text-amber-300/90 tabular-nums">
                {needsYou} waiting
              </span>
            )}
          </span>
        )}
        <span
          className={cn(
            "line-clamp-2 font-medium leading-snug text-balance text-zinc-100",
            isFeature ? "text-base" : "text-[13px]",
          )}
        >
          {brief.headline}
        </span>
        {isFeature && brief.lede && (
          <span className="line-clamp-2 text-xs leading-relaxed text-pretty text-zinc-400">
            {brief.lede}
          </span>
        )}
        {edition && (
          <span className="mt-auto truncate pt-0.5 text-xs text-zinc-500">
            {edition}
          </span>
        )}
      </span>
    </Button>
  );
}
