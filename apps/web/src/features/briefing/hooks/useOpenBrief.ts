"use client";

import { useOverlayState } from "@heroui/react";
import type { BriefingView } from "@shared/api/generated";
import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { isNotFound } from "@/lib/api/errorMessage";

import { briefingQuery } from "../api/briefingApi";
import type { FoldedBriefSummary } from "../utils/briefCard";
import {
  type EditionHold,
  type EditionLayout,
  holdEdition,
  type PreparedEdition,
  prepareEdition,
} from "../utils/preparedEdition";

/** The rendered edition unfolds as a letter; a brief with no edition opens as its text sheet. */
export type OpenedBrief =
  | { kind: "edition"; edition: PreparedEdition }
  | { kind: "text"; briefing: BriefingView }
  | { kind: "missing" }
  | { kind: "failed" };

/** What a trigger gets: open the letter (from where it lies), ready it ahead of a press, and its state. */
export interface BriefTriggerState {
  open: (origin?: DOMRect) => void;
  warm: () => void;
  /** The letter is being prepared; a second press waits for it. */
  isBusy: boolean;
  /** The letter has left its place on the page to lie open above it. */
  isLifted: boolean;
}

/**
 * Opening one folded brief: its edition readied on hover, fetched and cut on
 * press, held while it lies open, and released when the next one opens or the
 * trigger leaves the page. A brief that is gone opens as "missing"; any other
 * failed read opens as "failed", which the reader can retry.
 */
export function useOpenBrief(brief: FoldedBriefSummary, briefingId: string) {
  const { imageUrl, editionFold, editionPaper } = brief;
  const layout: EditionLayout = useMemo(
    () => ({ fold: editionFold, paper: editionPaper }),
    [editionFold, editionPaper],
  );
  const queryClient = useQueryClient();
  const overlay = useOverlayState();
  const [opened, setOpened] = useState<OpenedBrief | null>(null);
  const [isBusy, setIsBusy] = useState(false);
  const [origin, setOrigin] = useState<DOMRect | null>(null);
  const [isLifted, setIsLifted] = useState(false);
  // The open letter's edition stays prepared, its bitmaps open, until it has folded away.
  const heldEdition = useRef<EditionHold | null>(null);
  const release = useCallback(() => {
    heldEdition.current?.release();
    heldEdition.current = null;
  }, []);
  const settle = useCallback(() => {
    setIsLifted(false);
    release();
  }, [release]);

  useEffect(() => release, [release]);

  const hold = (src: string, editionLayout: EditionLayout) => {
    const next = holdEdition(src, editionLayout);
    release();
    heldEdition.current = next;
    return next.edition;
  };

  const warm = () => {
    if (!imageUrl) return;
    prepareEdition(imageUrl, layout).catch((error: unknown) =>
      console.error("Preparing the briefing edition failed", error),
    );
  };

  const resolve = async (): Promise<OpenedBrief> => {
    // The edition it carries is already cut, so it opens at once; the brief is still
    // fetched alongside, which is what marks it opened.
    if (imageUrl) {
      const edition = await hold(imageUrl, layout).catch(() => null);
      if (edition) {
        void queryClient.prefetchQuery(briefingQuery(briefingId));
        return { kind: "edition", edition };
      }
    }
    const read = await queryClient.fetchQuery(briefingQuery(briefingId)).then(
      (briefing) => ({ briefing }),
      (error: unknown) => ({ error }),
    );
    if ("error" in read)
      return { kind: isNotFound(read.error) ? "missing" : "failed" };
    const { briefing } = read;
    // A note has no edition, so it opens as its text.
    const { edition } = briefing.card;
    if (edition) {
      try {
        return {
          kind: "edition",
          edition: await hold(edition.image_url, edition),
        };
      } catch (error) {
        // The stored edition no longer loads; the brief's text is the same content.
        console.error("Briefing edition image failed to load", error);
      }
    }
    return { kind: "text", briefing };
  };

  const open = async (from?: DOMRect) => {
    if (isBusy) return;
    setIsBusy(true);
    try {
      setOpened(await resolve());
      setOrigin(from ?? null);
      setIsLifted(Boolean(from));
      overlay.open();
    } finally {
      setIsBusy(false);
    }
  };

  const retry = async () => {
    setIsBusy(true);
    try {
      setOpened(await resolve());
    } finally {
      setIsBusy(false);
    }
  };

  const trigger: BriefTriggerState = {
    open: (from) => void open(from),
    warm,
    isBusy,
    isLifted,
  };

  return {
    trigger,
    opened,
    origin,
    isOpen: overlay.isOpen,
    close: overlay.close,
    retry: () => void retry(),
    /** Called once the letter has folded back to where it lay. */
    settle,
  };
}
