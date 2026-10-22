"use client";

import { Button } from "@heroui/button";
import { Skeleton } from "@heroui/skeleton";
import { Cancel01Icon, NewsIcon } from "@icons";
import { format, parseISO } from "date-fns";
import Image from "next/image";
import { useState } from "react";

import { LetterModal } from "@/components/shared/LetterModal";
import { cn } from "@/lib/utils";

import { useBriefingQuery } from "../hooks/useBriefingQuery";
import {
  BriefingEdition,
  type BriefingEditionPayload,
} from "./BriefingEdition";

const THUMB_WIDTH = 52;
const THUMB_HEIGHT = 68;

const TONE_CLASSES = {
  raised: "bg-zinc-800 hover:bg-zinc-700/70",
  inset: "bg-zinc-900 hover:bg-zinc-950/70",
} as const;

/** What the open sheet shows: the brief itself, or the id to load it by. */
type BriefingFoldContent =
  | { payload: BriefingEditionPayload; briefingId?: never }
  | { briefingId: string; payload?: never };

export type BriefingFoldProps = BriefingFoldContent & {
  headline: string;
  /** ISO day of the brief (YYYY-MM-DD). */
  date?: string;
  imageUrl?: string | null;
  /** "raised" on the page background, "inset" inside a zinc-800 card. */
  tone?: keyof typeof TONE_CLASSES;
};

function EditionById({ briefingId }: { briefingId: string }) {
  const { data: briefing, isLoading, isError } = useBriefingQuery(briefingId);
  if (isLoading) return <Skeleton className="h-[70vh] w-full rounded-2xl" />;
  if (isError || !briefing) {
    return (
      <p className="rounded-2xl bg-zinc-800 p-4 text-sm text-zinc-400">
        This brief isn&apos;t available anymore.
      </p>
    );
  }
  return (
    <BriefingEdition
      payload={briefing.payload}
      imageUrl={briefing.edition_image_url}
    />
  );
}

/** A brief folded to its edition thumbnail and headline; pressing it opens the brief as a letter. */
export function BriefingFold({
  headline,
  date,
  imageUrl,
  tone = "raised",
  ...content
}: BriefingFoldProps) {
  const [isOpen, setIsOpen] = useState(false);
  const dateLabel = date ? format(parseISO(date), "EEEE, MMM d") : "Briefing";

  return (
    <>
      <Button
        disableRipple
        onPress={() => setIsOpen(true)}
        aria-label={`Open brief: ${headline}`}
        className={cn(
          "h-auto w-full max-w-md min-w-0 justify-start gap-3 rounded-2xl p-2.5 pr-4 text-left transition-colors data-[hover=true]:opacity-100",
          TONE_CLASSES[tone],
        )}
      >
        {imageUrl ? (
          <Image
            src={imageUrl}
            alt=""
            width={THUMB_WIDTH}
            height={THUMB_HEIGHT}
            className="h-[68px] w-[52px] shrink-0 rounded-lg object-cover object-top outline outline-1 -outline-offset-1 outline-white/10"
          />
        ) : (
          <span className="flex h-[68px] w-[52px] shrink-0 items-center justify-center rounded-lg bg-zinc-700/60">
            <NewsIcon className="size-5 text-zinc-400" />
          </span>
        )}
        <span className="flex min-w-0 flex-1 flex-col gap-0.5">
          <span className="text-xs text-zinc-500">{dateLabel}</span>
          <span className="line-clamp-2 text-sm font-medium whitespace-normal text-zinc-100">
            {headline}
          </span>
        </span>
      </Button>

      <LetterModal
        isOpen={isOpen}
        onClose={() => setIsOpen(false)}
        ariaLabel={headline}
      >
        <div className="relative">
          <Button
            isIconOnly
            size="sm"
            radius="full"
            variant="flat"
            aria-label="Close the brief"
            onPress={() => setIsOpen(false)}
            className="absolute top-3 right-3 z-10 bg-black/40 text-zinc-200 backdrop-blur-sm"
          >
            <Cancel01Icon className="size-4" />
          </Button>
          {content.payload ? (
            <BriefingEdition payload={content.payload} imageUrl={imageUrl} />
          ) : (
            <EditionById briefingId={content.briefingId} />
          )}
        </div>
      </LetterModal>
    </>
  );
}
