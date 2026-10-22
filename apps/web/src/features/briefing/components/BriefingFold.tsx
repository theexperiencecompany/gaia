"use client";

import { Button } from "@heroui/button";
import { NewsIcon } from "@icons";
import { useQueryClient } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import { useReducedMotion, type Variants } from "motion/react";
import * as m from "motion/react-m";
import Image from "next/image";
import { useState } from "react";
import { preload } from "react-dom";

import { LetterModal } from "@/components/shared/LetterModal";
import { cn } from "@/lib/utils";

import { briefingQuery } from "../hooks/useBriefingQuery";
import {
  BriefingEdition,
  type BriefingEditionPayload,
} from "./BriefingEdition";
import { EditionUnfold } from "./EditionUnfold";

const THUMB_WIDTH = 52;
const THUMB_HEIGHT = 68;

const TONE_CLASSES = {
  raised: "bg-zinc-800 hover:bg-zinc-700/70",
  inset: "bg-zinc-900 hover:bg-zinc-950/70",
} as const;

const SHEET_VARIANTS: Variants = {
  enter: { opacity: 1, y: 0, transition: { duration: 0.3, ease: "easeOut" } },
  exit: { opacity: 0, y: 12, transition: { duration: 0.18, ease: "easeIn" } },
};

/** What the open view shows: the brief itself, or the id to load it by. */
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

/** The rendered edition unfolds as a letter; a brief with no edition opens as its text sheet. */
type OpenedBrief =
  | { kind: "edition"; src: string; aspect: number }
  | { kind: "text"; payload: BriefingEditionPayload }
  | { kind: "missing" };

/** Natural height over width, known only once the image has decoded. */
async function editionAspect(src: string): Promise<number> {
  const image = new window.Image();
  image.src = src;
  await image.decode();
  return image.naturalHeight / image.naturalWidth;
}

/** A brief folded to its edition thumbnail and headline; pressing it unfolds the edition above the page. */
export function BriefingFold({
  headline,
  date,
  imageUrl,
  tone = "raised",
  ...content
}: BriefingFoldProps) {
  const queryClient = useQueryClient();
  const reduceMotion = useReducedMotion();
  const [opened, setOpened] = useState<OpenedBrief | null>(null);
  const [isOpen, setIsOpen] = useState(false);
  const [isPreparing, setIsPreparing] = useState(false);
  const dateLabel = date ? format(parseISO(date), "EEEE, MMM d") : "Briefing";

  const warmEdition = () => {
    if (imageUrl) preload(imageUrl, { as: "image" });
  };

  const resolveBrief = async (): Promise<OpenedBrief> => {
    let payload = content.payload;
    let src = imageUrl;
    if (content.briefingId) {
      const briefing = await queryClient
        .fetchQuery(briefingQuery(content.briefingId))
        .catch(() => null);
      if (!briefing) return { kind: "missing" };
      payload = briefing.payload;
      src = briefing.edition_image_url;
    }
    if (!payload) return { kind: "missing" };
    if (src) {
      try {
        return { kind: "edition", src, aspect: await editionAspect(src) };
      } catch (error) {
        // The stored edition no longer loads; the brief's text is the same content.
        console.error("Briefing edition image failed to load", error);
      }
    }
    return { kind: "text", payload };
  };

  const open = async () => {
    if (isPreparing) return;
    setIsPreparing(true);
    try {
      setOpened(await resolveBrief());
      setIsOpen(true);
    } finally {
      setIsPreparing(false);
    }
  };

  return (
    <>
      <Button
        disableRipple
        onPress={open}
        onPointerEnter={warmEdition}
        onFocus={warmEdition}
        aria-label={`Open brief: ${headline}`}
        aria-busy={isPreparing}
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
        presentation="floating"
      >
        {opened?.kind === "edition" ? (
          <EditionUnfold
            src={opened.src}
            aspect={opened.aspect}
            alt={headline}
          />
        ) : (
          <m.div
            variants={reduceMotion ? undefined : SHEET_VARIANTS}
            className="w-[min(620px,calc(100vw-24px))] rounded-2xl shadow-[0_32px_80px_-24px_rgba(0,0,0,0.75)]"
          >
            {opened?.kind === "text" ? (
              <BriefingEdition payload={opened.payload} />
            ) : (
              <p className="rounded-2xl bg-zinc-800 p-4 text-sm text-zinc-400">
                This brief isn&apos;t available anymore.
              </p>
            )}
          </m.div>
        )}
      </LetterModal>
    </>
  );
}
