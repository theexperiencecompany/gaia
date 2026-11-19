"use client";

import { ArrowExpand01Icon } from "@icons";
import { useQueryClient } from "@tanstack/react-query";
import { useReducedMotion } from "motion/react";
import * as m from "motion/react-m";
import { type ReactNode, useCallback, useMemo, useState } from "react";

import { LetterModal } from "@/components/shared/LetterModal";
import { LinkButton } from "@/components/shared/LinkButton";
import { LETTER_CONTROL_PROPS } from "@/components/shared/letterControlProps";
import { LETTER_SHEET_VARIANTS } from "@/components/shared/letterMotion";
import { cn } from "@/lib/utils";

import { BRIEF_LETTER_WIDTH } from "../constants";
import { briefingQuery } from "../hooks/useBriefingQuery";
import {
  type EditionLayout,
  type PreparedEdition,
  prepareEdition,
} from "../utils/preparedEdition";
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

/**
 * What the open view shows: the brief itself, or the id to load it by. With an id
 * the open letter also offers the brief's full page.
 */
type BriefingFoldContent =
  | { payload: BriefingEditionPayload; briefingId?: string }
  | { briefingId: string; payload?: never };

/** What a custom trigger gets: open the letter in place, ready it ahead of a press, and whether it is being prepared. */
export interface BriefingFoldTrigger {
  open: () => void;
  warm: () => void;
  isBusy: boolean;
}

export type BriefingFoldProps = BriefingFoldContent & {
  brief: FoldedBriefSummary;
  /** "letter" is the bare folded paper GAIA's chat message carries; "card" the folded card everywhere else. */
  variant?: "card" | "letter";
  tone?: BriefCardTone;
  /** Draws the folded brief itself in place of the variants (a postmark's stamp, say). */
  renderTrigger?: (trigger: BriefingFoldTrigger) => ReactNode;
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
  renderTrigger,
  ...content
}: BriefingFoldProps) {
  const { headline, imageUrl } = brief;
  const { editionFold = null, editionPaper = null } = brief;
  const layout: EditionLayout = useMemo(
    () => ({ fold: editionFold, paper: editionPaper }),
    [editionFold, editionPaper],
  );
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
    prepareEdition(imageUrl, layout).catch((error: unknown) =>
      console.error("Preparing the briefing edition failed", error),
    );
  };

  const resolveBrief = async (): Promise<OpenedBrief> => {
    // The edition it carries is already cut, so it opens at once; the brief is still
    // fetched alongside, which is what marks it opened.
    if (content.briefingId && !content.payload && imageUrl) {
      const edition = await prepareEdition(imageUrl, layout).catch(() => null);
      if (edition) {
        void queryClient.prefetchQuery(briefingQuery(content.briefingId));
        return { kind: "edition", edition };
      }
    }
    let payload = content.payload;
    let src = imageUrl;
    let editionLayout = layout;
    if (content.briefingId && !payload) {
      const briefing = await queryClient
        .fetchQuery(briefingQuery(content.briefingId))
        .catch(() => null);
      if (!briefing) return { kind: "missing" };
      payload = briefing.payload;
      src = briefing.edition_image_url;
      editionLayout = {
        fold: briefing.edition_fold,
        paper: briefing.edition_paper,
      };
    }
    if (!payload) return { kind: "missing" };
    if (src) {
      try {
        return {
          kind: "edition",
          edition: await prepareEdition(src, editionLayout),
        };
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
      {renderTrigger ? (
        renderTrigger({
          open: () => void open(),
          warm: warmEdition,
          isBusy: isPreparing,
        })
      ) : variant === "letter" ? (
        <BriefLetter
          headline={headline}
          imageUrl={imageUrl}
          layout={layout}
          isBusy={isPreparing}
          isLifted={isLifted}
          onOpen={open}
        />
      ) : (
        <BriefCard
          brief={brief}
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
        actions={
          content.briefingId && opened?.kind !== "missing" ? (
            <LinkButton
              {...LETTER_CONTROL_PROPS}
              href={`/brief/${content.briefingId}`}
              className={cn(LETTER_CONTROL_PROPS.className, "font-medium")}
            >
              <ArrowExpand01Icon className="size-4" />
              Open full brief
            </LinkButton>
          ) : null
        }
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
            initial="arrive"
            animate="enter"
            exit="exit"
            variants={LETTER_SHEET_VARIANTS[reduceMotion ? "reduced" : "full"]}
            style={{ width: BRIEF_LETTER_WIDTH }}
            className="rounded-2xl shadow-[0_32px_80px_-24px_rgba(0,0,0,0.75)]"
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
