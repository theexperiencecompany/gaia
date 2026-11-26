"use client";

import { Skeleton } from "@heroui/react";
import { type MotionValue, motionValue, useInView } from "motion/react";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import { GaiaButton } from "@/components/shared/GaiaButton";
import { LETTER_HOVER_EASE } from "@/components/shared/letterMotion";
import { cn } from "@/lib/utils";

import type { BriefTriggerState } from "../hooks/useOpenBrief";
import {
  CHAT_LETTER_MAX_WIDTH_PX,
  LETTER_FOLD_PERSPECTIVE_PX,
  LETTER_TILT_DEG,
  LETTER_TILT_PERSPECTIVE_PX,
  RESTING_OPEN,
} from "../letterTokens";
import type { FoldedBriefSummary } from "../utils/briefCard";

import { holdEdition, type PreparedEdition } from "../utils/preparedEdition";
import { BriefTrigger } from "./BriefTrigger";
import { Panel } from "./LetterPanel";

/** Start preparing a little before the letter scrolls into view. */
const PREPARE_MARGIN = "240px";
/** A typical folded edition's width over height, held while the real one decodes. */
const PLACEHOLDER_ASPECT = 2.4;

/** An edition handed to the letter, with the hold that keeps its bitmaps open until the face is drawn. */
interface EditionDelivery {
  edition: PreparedEdition;
  release: () => void;
}

interface BriefLetterProps {
  /** Its edition, cut where the edition folds; the face ends at the fold. */
  brief: FoldedBriefSummary;
  /** Opened with where the front panel lies, so the open letter starts exactly there; hidden while it is lifted. */
  trigger: BriefTriggerState;
}

/** The room the sprung panels take below the front, as a share of the letter's width. */
const RESTING_SPRING_ROOM = 0.06;

function useRestingCreases(
  edition: PreparedEdition | null,
): MotionValue<number>[] {
  const count = edition?.panels.length ?? 0;
  return useMemo(
    () =>
      Array.from({ length: count }, (_, index) =>
        motionValue(index === 0 ? 1 : RESTING_OPEN),
      ),
    [count],
  );
}

/**
 * The edition folded in thirds and laid at a slight angle: its print on the face
 * down to the edition's own fold, the edge rolling under onto the sheet's plain
 * reverse. Its face is the unfold's first frame; hover lifts the sheet off the desk.
 */
export function BriefLetter({ brief, trigger }: BriefLetterProps) {
  const { headline, imageUrl, editionFold, editionPaper } = brief;
  const rootRef = useRef<HTMLDivElement>(null);
  const faceRef = useRef<HTMLSpanElement>(null);
  const isNear = useInView(rootRef, { margin: PREPARE_MARGIN });
  const [delivery, setDelivery] = useState<EditionDelivery | null>(null);
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  const isFailed = imageUrl !== null && failedUrl === imageUrl;
  const edition = delivery?.edition ?? null;
  const restingCreases = useRestingCreases(edition);

  // Each approach readies the edition again, so a press opens it at once; leaving lets it go.
  useEffect(() => {
    if (!isNear || !imageUrl || isFailed) return;
    let isCurrent = true;
    const hold = holdEdition(imageUrl, {
      fold: editionFold,
      paper: editionPaper,
    });
    hold.edition
      .then((prepared) => {
        if (isCurrent)
          setDelivery({ edition: prepared, release: hold.release });
      })
      .catch((error: unknown) => {
        console.error("Preparing the briefing letter failed", error);
        if (isCurrent) setFailedUrl(imageUrl);
      });
    return () => {
      isCurrent = false;
      hold.release();
    };
  }, [isNear, imageUrl, isFailed, editionFold, editionPaper]);

  // The face's canvas keeps what it drew (the face draws first, as a child), so the hold can go.
  useLayoutEffect(() => delivery?.release(), [delivery]);

  return (
    <div
      ref={rootRef}
      className="w-full pt-1 pb-5"
      style={{ maxWidth: CHAT_LETTER_MAX_WIDTH_PX }}
    >
      {edition ? (
        <BriefTrigger
          trigger={trigger}
          onPress={() => {
            if (faceRef.current)
              trigger.open(faceRef.current.getBoundingClientRect());
          }}
          aria-label={`Open brief: ${headline}`}
          className={cn(
            "group relative block h-auto w-full min-w-0 overflow-visible",
            trigger.isLifted && "invisible",
          )}
          style={{ perspective: LETTER_TILT_PERSPECTIVE_PX }}
        >
          <span
            aria-hidden
            className={cn(
              "absolute -inset-x-5 -bottom-4 h-10 rounded-[50%] bg-black/50 blur-2xl transition-[opacity,scale] duration-300",
              LETTER_HOVER_EASE,
              "group-hover:scale-x-105 group-hover:opacity-75",
            )}
          />
          <span
            aria-hidden
            className={cn(
              "absolute inset-x-3 -bottom-1 h-3 rounded-[50%] bg-black/55 blur-md transition-opacity duration-300",
              LETTER_HOVER_EASE,
              "group-hover:opacity-60",
            )}
          />
          <span
            className={cn(
              "relative block origin-top transition-[translate,scale] duration-300 group-hover:-translate-y-0.5 group-active:scale-[0.985]",
              LETTER_HOVER_EASE,
            )}
            style={{
              transform: `rotateX(${LETTER_TILT_DEG}deg)`,
              transformStyle: "preserve-3d",
            }}
          >
            <span
              ref={faceRef}
              className="relative z-10 block"
              style={{
                aspectRatio: `${1 / (edition.aspect * edition.shares[0])}`,
                marginBottom: `${RESTING_SPRING_ROOM * 100}%`,
              }}
            >
              <span
                className="absolute inset-x-0 top-0 block"
                style={{
                  height: `${100 / edition.shares[0]}%`,
                  perspective: LETTER_FOLD_PERSPECTIVE_PX,
                  perspectiveOrigin: "50% 0%",
                  transformStyle: "preserve-3d",
                }}
              >
                <Panel index={0} edition={edition} creases={restingCreases} />
              </span>
            </span>
          </span>
        </BriefTrigger>
      ) : !imageUrl || isFailed ? (
        <GaiaButton
          variant="default-soft"
          shape="sm"
          fullWidth
          className="h-auto min-h-11 justify-start text-left text-sm whitespace-normal"
          aria-busy={trigger.isBusy}
          onPress={() => {
            if (rootRef.current)
              trigger.open(rootRef.current.getBoundingClientRect());
          }}
        >
          {headline}
        </GaiaButton>
      ) : (
        <Skeleton
          className="w-full rounded-[3px]"
          style={{ aspectRatio: `${PLACEHOLDER_ASPECT}` }}
        />
      )}
    </div>
  );
}
