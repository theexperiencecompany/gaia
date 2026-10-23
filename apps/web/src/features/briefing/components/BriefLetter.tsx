"use client";

import { Button } from "@heroui/button";
import { Skeleton } from "@heroui/skeleton";
import { useInView } from "motion/react";
import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

import {
  type EditionLayout,
  LETTER_MAX_WIDTH,
  LETTER_PERSPECTIVE_PX,
  LETTER_TILT_DEG,
  type PreparedEdition,
  prepareEdition,
} from "../utils/preparedEdition";
import { PanelFace } from "./EditionUnfold";

/** Fine paper fibre: fractal noise, multiplied faintly over the face. */
const PAPER_GRAIN = `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='160' height='160'%3E%3Cfilter id='g'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/%3E%3CfeColorMatrix values='0 0 0 0 0.5 0 0 0 0 0.45 0 0 0 0 0.4 0 0 0 0.5 0'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23g)'/%3E%3C/svg%3E")`;
/** Start preparing a little before the letter scrolls into view. */
const PREPARE_MARGIN = "240px";
/** A typical folded edition's width over height, held while the real one decodes. */
const PLACEHOLDER_ASPECT = 2.4;
const EASE_OUT = "ease-[cubic-bezier(0.23,1,0.32,1)]";
/** The reverse of the sheet reads a touch cooler than its printed face. */
const REVERSE_TINT = "rgb(52, 64, 88)";
const CREASE_PX = 6;
/** The two folded-under panels show as the sheet's unprinted reverse, each a little deeper back. */
const FOLDED_LAYERS = [
  { heightPx: 8, tint: 90, nudgeXPx: 0, turnDeg: 0, inset: 0 },
  { heightPx: 7, tint: 83, nudgeXPx: 1, turnDeg: 0.3, inset: 0.6 },
] as const;

interface BriefLetterProps {
  headline: string;
  imageUrl?: string | null;
  /** Where the edition folds and where its paper lies; the face ends at the fold. */
  layout: EditionLayout;
  isBusy?: boolean;
  /** Hidden while the letter itself is open above the page, so it is never in two places. */
  isLifted?: boolean;
  /** Called with where the front panel lies, so the open letter starts exactly there. */
  onOpen: (origin: DOMRect) => void;
}

function mix(paper: string, share: number, toward: string): string {
  return `color-mix(in srgb, ${paper} ${share}%, ${toward})`;
}

/** The front's bottom edge rolling under: a highlight on the curve, shading as it turns away. */
function Crease({ edition }: { edition: PreparedEdition }) {
  const { paper, isDarkPaper } = edition;
  return (
    <span
      aria-hidden
      className="relative z-10 block rounded-b-[5px]"
      style={{
        height: CREASE_PX,
        background: `linear-gradient(180deg, ${paper} 0%, ${mix(paper, isDarkPaper ? 82 : 88, "white")} 30%, ${mix(paper, 78, "black")} 85%, ${mix(paper, 66, "black")} 100%)`,
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
  const edgeLight = isDarkPaper
    ? "rgba(255,255,255,0.12)"
    : "rgba(255,255,255,0.4)";
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
            background: mix(paper, layer.tint, REVERSE_TINT),
          }}
        >
          <span
            className="absolute inset-0 opacity-30 mix-blend-multiply"
            style={{ backgroundImage: PAPER_GRAIN }}
          />
          <span
            className="absolute inset-0"
            style={{
              background: `linear-gradient(180deg, rgba(0,0,0,${isDarkPaper ? 0.5 : 0.32}) 0%, rgba(0,0,0,0.08) 55%, transparent 100%)`,
            }}
          />
          <span
            className="absolute inset-x-0 bottom-0 h-px"
            style={{ background: edgeLight }}
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
export function BriefLetter({
  headline,
  imageUrl,
  layout,
  isBusy = false,
  isLifted = false,
  onOpen,
}: BriefLetterProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  const faceRef = useRef<HTMLSpanElement>(null);
  const isNear = useInView(rootRef, { once: true, margin: PREPARE_MARGIN });
  const [edition, setEdition] = useState<PreparedEdition | null>(null);

  useEffect(() => {
    if (!isNear || !imageUrl) return;
    let isCurrent = true;
    prepareEdition(imageUrl, layout)
      .then((prepared) => {
        if (isCurrent) setEdition(prepared);
      })
      .catch((error: unknown) =>
        console.error("Preparing the briefing letter failed", error),
      );
    return () => {
      isCurrent = false;
    };
  }, [isNear, imageUrl, layout]);

  return (
    <div
      ref={rootRef}
      className="w-full pt-1 pb-5"
      style={{ maxWidth: LETTER_MAX_WIDTH }}
    >
      {edition ? (
        <Button
          disableRipple
          onPress={() => {
            if (faceRef.current)
              onOpen(faceRef.current.getBoundingClientRect());
          }}
          aria-label={`Open brief: ${headline}`}
          aria-busy={isBusy}
          className={cn(
            "group relative block h-auto w-full min-w-0 overflow-visible rounded-none bg-transparent p-0 data-[hover=true]:bg-transparent",
            isLifted && "invisible",
          )}
          style={{ perspective: LETTER_PERSPECTIVE_PX }}
        >
          <span
            aria-hidden
            className={cn(
              "absolute -inset-x-5 -bottom-4 h-10 rounded-[50%] bg-black/50 blur-2xl transition-[opacity,scale] duration-300",
              EASE_OUT,
              "group-data-[hover=true]:scale-x-105 group-data-[hover=true]:opacity-75",
            )}
          />
          <span
            aria-hidden
            className={cn(
              "absolute inset-x-3 -bottom-1 h-3 rounded-[50%] bg-black/55 blur-md transition-opacity duration-300",
              EASE_OUT,
              "group-data-[hover=true]:opacity-60",
            )}
          />
          <span
            className={cn(
              "relative block origin-top transition-[translate,scale] duration-300 group-data-[hover=true]:-translate-y-0.5 group-data-[pressed=true]:scale-[0.985]",
              EASE_OUT,
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
                  background: edition.isDarkPaper
                    ? "rgba(255,255,255,0.25)"
                    : "rgba(255,255,255,0.7)",
                }}
              />
            </span>
            <Crease edition={edition} />
            <FoldedPanels edition={edition} />
          </span>
        </Button>
      ) : (
        <Skeleton
          className="w-full rounded-[3px]"
          style={{ aspectRatio: `${PLACEHOLDER_ASPECT}` }}
        />
      )}
    </div>
  );
}
