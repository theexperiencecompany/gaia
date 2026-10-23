"use client";

import { Button } from "@heroui/button";
import { Skeleton } from "@heroui/skeleton";
import { useInView } from "motion/react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

import {
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
/** The two folded-under panels: each steps in from the sides, shows less, and sits in more shade. */
const FOLDED_LAYERS = [
  { inset: 2.5, heightPx: 10, shade: 0.06 },
  { inset: 5, heightPx: 8, shade: 0.12 },
] as const;

interface BriefLetterProps {
  headline: string;
  imageUrl?: string | null;
  isBusy?: boolean;
  /** Hidden while the letter itself is open above the page, so it is never in two places. */
  isLifted?: boolean;
  /** Called with where the front panel lies, so the open letter starts exactly there. */
  onOpen: (origin: DOMRect) => void;
}

/** The two folded-under panels' edges below the face, each a paper's thickness further back. */
/** The top of a folded-under panel, cut to the sliver that shows below the one in front. */
function PanelSliver({
  bitmap,
  heightPx,
}: {
  bitmap: ImageBitmap;
  heightPx: number;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const sliverHeight = Math.round(heightPx * (window.devicePixelRatio || 1));
  useLayoutEffect(() => {
    const canvas = canvasRef.current;
    const context = canvas?.getContext("2d");
    if (!canvas || !context) return;
    // The sliver shows as much of the panel's top as its height covers at the strip's width.
    const sourceHeight = (heightPx * bitmap.width) / canvas.clientWidth;
    context.drawImage(
      bitmap,
      0,
      0,
      bitmap.width,
      sourceHeight,
      0,
      0,
      bitmap.width,
      sliverHeight,
    );
  }, [bitmap, sliverHeight]);
  return (
    <canvas
      ref={canvasRef}
      width={bitmap.width}
      height={sliverHeight}
      className="absolute inset-0 h-full w-full"
    />
  );
}

/**
 * The folded-under panels below the face: the same paper stepping back and in,
 * each a little darker, its top edge of content showing, a fine shadow between.
 */
function FoldedEdges({ edition }: { edition: PreparedEdition }) {
  const { paper, isDarkPaper, panels } = edition;
  const crease = isDarkPaper
    ? "rgba(255,255,255,0.3)"
    : "rgba(255,255,255,0.75)";
  return (
    <>
      {FOLDED_LAYERS.map((layer, depth) => {
        const bitmap = panels[depth + 1];
        if (!bitmap) return null;
        return (
          <span
            key={layer.inset}
            aria-hidden
            className="relative block overflow-hidden rounded-b-[5px]"
            style={{
              marginInline: `${layer.inset}%`,
              height: layer.heightPx,
              background: paper,
              boxShadow: `0 1px 1.5px rgba(0,0,0,${isDarkPaper ? 0.5 : 0.3}), inset 0 1px 0 ${crease}`,
            }}
          >
            <PanelSliver bitmap={bitmap} heightPx={layer.heightPx} />
            <span
              className="absolute inset-0"
              style={{
                background: `linear-gradient(180deg, rgba(0,0,0,${layer.shade + 0.12}) 0%, rgba(0,0,0,${layer.shade}) 55%, rgba(0,0,0,${layer.shade + 0.04}) 100%)`,
              }}
            />
          </span>
        );
      })}
    </>
  );
}

/**
 * The edition folded in thirds and laid at a slight angle: the paper's top third
 * on the face, the two folded-under panels stepping out beneath it. Its face is
 * the unfold's first frame; hover lifts it and eases the face open a touch.
 */
export function BriefLetter({
  headline,
  imageUrl,
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
    prepareEdition(imageUrl)
      .then((prepared) => {
        if (isCurrent) setEdition(prepared);
      })
      .catch((error: unknown) =>
        console.error("Preparing the briefing letter failed", error),
      );
    return () => {
      isCurrent = false;
    };
  }, [isNear, imageUrl]);

  return (
    <div
      ref={rootRef}
      className="w-full pt-1 pb-4"
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
              "absolute inset-x-6 -bottom-2 h-6 rounded-[50%] bg-black/60 blur-xl transition-[opacity,translate] duration-300",
              EASE_OUT,
              "group-data-[hover=true]:translate-y-1 group-data-[hover=true]:opacity-80",
            )}
          />
          <span
            className={cn(
              "relative block origin-top transition-transform duration-300 group-data-[pressed=true]:scale-[0.985]",
              EASE_OUT,
            )}
            style={{
              transform: `rotateX(${LETTER_TILT_DEG}deg)`,
              transformStyle: "preserve-3d",
            }}
          >
            <span
              ref={faceRef}
              className={cn(
                "relative block origin-bottom overflow-hidden rounded-t-[3px] transition-transform duration-300",
                EASE_OUT,
                "group-data-[hover=true]:[transform:translateY(-3px)_rotateX(-5deg)]",
              )}
              style={{
                aspectRatio: `${edition.panels.length / edition.aspect}`,
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
            <FoldedEdges edition={edition} />
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
