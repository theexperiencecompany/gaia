"use client";

import { Button } from "@heroui/button";
import { Skeleton } from "@heroui/skeleton";
import { useInView } from "motion/react";
import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

import {
  LETTER_MAX_WIDTH,
  type PreparedEdition,
  prepareEdition,
} from "../utils/preparedEdition";
import { PanelFace } from "./EditionUnfold";

/** Fine paper fibre: fractal noise, multiplied faintly over the face. */
const PAPER_GRAIN = `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='160' height='160'%3E%3Cfilter id='g'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/%3E%3CfeColorMatrix values='0 0 0 0 0.5 0 0 0 0 0.45 0 0 0 0 0.4 0 0 0 0.5 0'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23g)'/%3E%3C/svg%3E")`;
/** Start preparing a little before the letter scrolls into view. */
const PREPARE_MARGIN = "240px";
/** A typical folded edition's width over height, held while the real one decodes. */
const PLACEHOLDER_ASPECT = 2.2;

interface BriefLetterProps {
  headline: string;
  imageUrl?: string | null;
  isBusy?: boolean;
  /** Hidden while the letter itself is open above the page, so it is never in two places. */
  isLifted?: boolean;
  /** Called with where the front panel lies, so the open letter starts exactly there. */
  onOpen: (origin: DOMRect) => void;
}

function shade(paper: string, share: number): string {
  return `color-mix(in srgb, ${paper} ${share}%, black)`;
}

/** A crease's catch of light on the paper's folded edge. */
function lighten(paper: string, share: number): string {
  return `color-mix(in srgb, ${paper} ${share}%, white)`;
}

/**
 * The edition folded in thirds, seen from the front: its top third on the face,
 * the two folded panels showing as edges at the top and bottom creases. Its face
 * is the unfold's first frame; hover lifts it and eases the face open a touch.
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

  const count = edition?.panels.length ?? 3;
  const ratio = edition ? count / edition.aspect : PLACEHOLDER_ASPECT;
  const paper = edition?.paper ?? "rgb(228, 223, 212)";

  return (
    <div
      ref={rootRef}
      className="w-full py-1.5"
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
            "group relative block h-auto w-full min-w-0 overflow-visible rounded-[6px] bg-transparent p-0 [perspective:900px]",
            "transition-[translate,scale] duration-300 ease-[cubic-bezier(0.23,1,0.32,1)] data-[hover=true]:-translate-y-[3px] data-[hover=true]:bg-transparent data-[pressed=true]:scale-[0.985]",
            isLifted && "invisible",
          )}
          style={{ aspectRatio: `${ratio}` }}
        >
          <span
            aria-hidden
            className="absolute inset-x-[7px] -top-[6px] bottom-[8px] rounded-[6px]"
            style={{
              background: `linear-gradient(180deg, ${lighten(paper, 80)} 0%, ${shade(paper, 86)} 40%)`,
              boxShadow:
                "inset 0 1px 0 rgba(255,255,255,0.6), 0 -1px 2px rgba(0,0,0,0.25)",
            }}
          />
          <span
            aria-hidden
            className="absolute inset-x-[3px] top-[8px] -bottom-[7px] rounded-[6px] shadow-[0_1px_1px_rgba(0,0,0,0.35),0_8px_16px_-6px_rgba(0,0,0,0.5),0_26px_44px_-18px_rgba(0,0,0,0.65)] transition-shadow duration-300 group-data-[hover=true]:shadow-[0_1px_1px_rgba(0,0,0,0.35),0_14px_24px_-8px_rgba(0,0,0,0.55),0_38px_60px_-20px_rgba(0,0,0,0.7)]"
            style={{
              background: `linear-gradient(180deg, ${shade(paper, 88)} 0%, ${shade(paper, 76)} 85%, ${lighten(paper, 82)} 100%)`,
            }}
          />
          <span
            ref={faceRef}
            className="absolute inset-0 origin-bottom overflow-hidden rounded-[6px] shadow-[0_1px_2px_rgba(0,0,0,0.3)] transition-transform duration-300 ease-[cubic-bezier(0.23,1,0.32,1)] group-data-[hover=true]:[transform:rotateX(-7deg)]"
            style={{ background: paper }}
          >
            <PanelFace bitmap={edition.panels[0]} />
            <span
              aria-hidden
              className="absolute inset-0 opacity-30 mix-blend-multiply"
              style={{ backgroundImage: PAPER_GRAIN }}
            />
            <span
              aria-hidden
              className="absolute inset-0 bg-gradient-to-b from-white/[0.07] via-transparent to-black/[0.08]"
            />
            <span
              aria-hidden
              className="absolute inset-x-0 top-0 h-px bg-white/60"
            />
            <span
              aria-hidden
              className="absolute inset-x-0 bottom-0 h-6 bg-gradient-to-b from-transparent to-black/20"
            />
            <span
              aria-hidden
              className="absolute inset-x-0 bottom-0 h-px bg-white/50"
            />
          </span>
        </Button>
      ) : (
        <Skeleton
          className="w-full rounded-[6px]"
          style={{ aspectRatio: `${ratio}` }}
        />
      )}
    </div>
  );
}
