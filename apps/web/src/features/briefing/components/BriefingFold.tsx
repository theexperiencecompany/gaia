"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useReducedMotion, type Variants } from "motion/react";
import * as m from "motion/react-m";
import { useCallback, useState } from "react";

import { LetterModal } from "@/components/shared/LetterModal";

import { briefingQuery } from "../hooks/useBriefingQuery";
import { type PreparedEdition, prepareEdition } from "../utils/preparedEdition";
import {
  BriefCard,
  type BriefCardTone,
  type FoldedBriefSummary,
} from "./BriefCard";
import {
  BriefingEdition,
  type BriefingEditionPayload,
} from "./BriefingEdition";
import { BriefLetter } from "./BriefLetter";
import { EditionUnfold } from "./EditionUnfold";

const SHEET_VARIANTS: Variants = {
  enter: { opacity: 1, y: 0, transition: { duration: 0.3, ease: "easeOut" } },
  exit: { opacity: 0, y: 12, transition: { duration: 0.18, ease: "easeIn" } },
};

/** What the open view shows: the brief itself, or the id to load it by. */
type BriefingFoldContent =
  | { payload: BriefingEditionPayload; briefingId?: never }
  | { briefingId: string; payload?: never };

export type BriefingFoldProps = BriefingFoldContent & {
  brief: FoldedBriefSummary;
  /** "letter" is the bare folded paper GAIA's chat message carries; the others are archive cards. */
  variant?: "card" | "feature" | "letter";
  tone?: BriefCardTone;
};

/** The rendered edition unfolds as a letter; a brief with no edition opens as its text sheet. */
type OpenedBrief =
  | { kind: "edition"; edition: PreparedEdition }
  | { kind: "text"; payload: BriefingEditionPayload }
  | { kind: "missing" };

/** A brief folded to a letter card; pressing it unfolds the edition above the page. */
export function BriefingFold({
  brief,
  variant,
  tone,
  ...content
}: BriefingFoldProps) {
  const { headline, imageUrl } = brief;
  const queryClient = useQueryClient();
  const reduceMotion = useReducedMotion();
  const [opened, setOpened] = useState<OpenedBrief | null>(null);
  const [isOpen, setIsOpen] = useState(false);
  const [isPreparing, setIsPreparing] = useState(false);
  const [origin, setOrigin] = useState<DOMRect | null>(null);
  const [isLifted, setIsLifted] = useState(false);
  const settleLetter = useCallback(() => setIsLifted(false), []);

  const warmEdition = () => {
    if (!imageUrl) return;
    prepareEdition(imageUrl).catch((error: unknown) =>
      console.error("Preparing the briefing edition failed", error),
    );
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
        return { kind: "edition", edition: await prepareEdition(src) };
      } catch (error) {
        // The stored edition no longer loads; the brief's text is the same content.
        console.error("Briefing edition image failed to load", error);
      }
    }
    return { kind: "text", payload };
  };

  const open = async (from?: DOMRect) => {
    if (isPreparing) return;
    setIsPreparing(true);
    try {
      setOpened(await resolveBrief());
      setOrigin(from ?? null);
      setIsLifted(Boolean(from));
      setIsOpen(true);
    } finally {
      setIsPreparing(false);
    }
  };

  return (
    <>
      {variant === "letter" ? (
        <BriefLetter
          headline={headline}
          imageUrl={imageUrl}
          isBusy={isPreparing}
          isLifted={isLifted}
          onOpen={open}
        />
      ) : (
        <BriefCard
          brief={brief}
          variant={variant}
          tone={tone}
          isBusy={isPreparing}
          onPress={() => open()}
          onWarm={warmEdition}
        />
      )}

      <LetterModal
        isOpen={isOpen}
        onClose={() => setIsOpen(false)}
        ariaLabel={headline}
        presentation="floating"
      >
        {opened?.kind === "edition" ? (
          <EditionUnfold
            edition={opened.edition}
            alt={headline}
            origin={origin}
            onFolded={settleLetter}
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
