"use client";

import { Skeleton } from "@heroui/react";
import { useInView } from "motion/react";
import { useEffect, useRef, useState } from "react";

import { GaiaButton } from "@/components/shared/GaiaButton";
import { LETTER_HOVER_EASE } from "@/components/shared/letterMotion";
import { cn } from "@/lib/utils";

import type { BriefTriggerState } from "../hooks/useOpenBrief";
import {
  CHAT_LETTER_MAX_WIDTH_PX,
  LETTER_TILT_DEG,
  LETTER_TILT_PERSPECTIVE_PX,
} from "../letterTokens";
import {
  edgeLight,
  foldedReverse,
  PAPER_GRAIN,
  rolledEdge,
  underFoldShadow,
} from "../paperMaterial";
import type { FoldedBriefSummary } from "../utils/briefCard";

import { holdEdition, type PreparedEdition } from "../utils/preparedEdition";
import { BriefTrigger } from "./BriefTrigger";
import { PanelFace } from "./EditionUnfold";

/** Start preparing a little before the letter scrolls into view. */
const PREPARE_MARGIN = "240px";
/** A typical folded edition's width over height, held while the real one decodes. */
const PLACEHOLDER_ASPECT = 2.4;
const CREASE_PX = 6;
/** The two folded-under panels show as the sheet's unprinted reverse, each a little deeper back. */
const FOLDED_LAYERS = [
  { heightPx: 8, tint: 90, nudgeXPx: 0, turnDeg: 0, inset: 0 },
  { heightPx: 7, tint: 83, nudgeXPx: 1, turnDeg: 0.3, inset: 0.6 },
] as const;

interface BriefLetterProps {
  /** Its edition, cut where the edition folds; the face ends at the fold. */
  brief: FoldedBriefSummary;
  /** Opened with where the front panel lies, so the open letter starts exactly there; hidden while it is lifted. */
  trigger: BriefTriggerState;
}

/** The front's bottom edge rolling under onto the folded panels. */
function RolledEdge({ edition }: { edition: PreparedEdition }) {
  return (
    <span
      aria-hidden
      className="relative z-10 block rounded-b-[5px]"
      style={{
        height: CREASE_PX,
        background: rolledEdge(edition.paper, edition.isDarkPaper),
      }}
    />
  );
}

/**
 * The folded-under panels: the sheet's reverse, same paper and grain without the
 * print, in the front's shadow just under the crease, the back one set a hair askew.
 */
function FoldedPanels({ edition }: { edition: PreparedEdition }) {
  const { paper, isDarkPaper } = edition;
  return (
    <>
      {FOLDED_LAYERS.map((layer, depth) => (
        <span
          key={layer.heightPx}
          aria-hidden
          className="relative block overflow-hidden rounded-b-[4px]"
          style={{
            height: layer.heightPx,
            marginInline: `${layer.inset}%`,
            marginTop: depth === 0 ? -2 : -1,
            zIndex: -depth,
            transform: `translateX(${layer.nudgeXPx}px) rotate(${layer.turnDeg}deg)`,
            background: foldedReverse(paper, layer.tint),
          }}
        >
          <span
            className="absolute inset-0 opacity-30 mix-blend-multiply"
            style={{ backgroundImage: PAPER_GRAIN }}
          />
          <span
            className="absolute inset-0"
            style={{ background: underFoldShadow(isDarkPaper) }}
          />
          <span
            className="absolute inset-x-0 bottom-0 h-px"
            style={{ background: edgeLight("fold", isDarkPaper) }}
          />
        </span>
      ))}
    </>
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
  const isNear = useInView(rootRef, { once: true, margin: PREPARE_MARGIN });
  const [edition, setEdition] = useState<PreparedEdition | null>(null);
  const [isFailed, setIsFailed] = useState(false);

  useEffect(() => {
    if (!isNear || !imageUrl) return;
    let isCurrent = true;
    setIsFailed(false);
    const hold = holdEdition(imageUrl, {
      fold: editionFold,
      paper: editionPaper,
    });
    hold.edition
      .then((prepared) => {
        if (isCurrent) setEdition(prepared);
      })
      .catch((error: unknown) => {
        console.error("Preparing the briefing letter failed", error);
        if (isCurrent) setIsFailed(true);
      });
    return () => {
      isCurrent = false;
      hold.release();
    };
  }, [isNear, imageUrl, editionFold, editionPaper]);

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
              className="relative z-10 block overflow-hidden rounded-t-[3px]"
              style={{
                aspectRatio: `${1 / (edition.aspect * edition.shares[0])}`,
                background: edition.paper,
                // A hairline of the paper's own colour keeps the tilted edge from picking up the page.
                boxShadow: `0 0 0 0.5px ${edition.paper}`,
                outline: "1px solid transparent",
              }}
            >
              <PanelFace bitmap={edition.panels[0]} />
              <span
                aria-hidden
                className="absolute inset-0 opacity-30 mix-blend-multiply"
                style={{ backgroundImage: PAPER_GRAIN }}
              />
              <span
                aria-hidden
                className="absolute inset-x-0 top-0 h-px"
                style={{
                  background: edgeLight("face", edition.isDarkPaper),
                }}
              />
            </span>
            <RolledEdge edition={edition} />
            <FoldedPanels edition={edition} />
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
