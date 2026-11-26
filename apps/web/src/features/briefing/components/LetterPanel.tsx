"use client";

import { type MotionValue, useTransform } from "motion/react";
import * as m from "motion/react-m";
import { useLayoutEffect, useRef } from "react";

import { cn } from "@/lib/utils";
import { panelBack } from "../paperMaterial";
import type { PreparedEdition } from "../utils/preparedEdition";

/** A panel stops short of a flat 180deg fold so stacked panels never z-fight. */
const FOLDED_DEG = 177;
export const CORNER_RADIUS_PX = 8;
/** Each lower panel reaches this far up under the one above, so no hairline of page shows at the crease. */
const SEAM_OVERLAP_PX = 1;
/** Accordion fold: each crease bends the opposite way to the one above it. */
function foldedAngle(index: number): number {
  return index % 2 === 1 ? -FOLDED_DEG : FOLDED_DEG;
}

/** The shading a crease casts on the panel below it; both fade to nothing as the panel lies flat. */
function CreaseShade({
  fold,
  isDarkPaper,
}: {
  fold: MotionValue<number>;
  isDarkPaper: boolean;
}) {
  const shade = useTransform(fold, [0, 1], [0, 0.5]);
  const valley = useTransform(fold, [0, 0.6], [0, 1], { clamp: true });
  return (
    <>
      <m.div
        aria-hidden
        className="pointer-events-none absolute inset-0 bg-black"
        style={{ opacity: shade }}
      />
      <m.div
        aria-hidden
        className={cn(
          "pointer-events-none absolute inset-x-0 top-0 h-8 bg-gradient-to-b to-transparent",
          isDarkPaper ? "from-white/15" : "from-black/30",
        )}
        style={{ opacity: valley }}
      />
    </>
  );
}

/**
 * A panel's slice, already cut at display resolution, drawn once into its own
 * small canvas. The canvas keeps what it drew, so the bitmap may be closed after.
 */
export function PanelFace({ bitmap }: { bitmap: ImageBitmap }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  useLayoutEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    // Sized here, not as props: a closed bitmap reads 0 wide, and resizing would wipe the drawing.
    canvas.width = bitmap.width;
    canvas.height = bitmap.height;
    canvas.getContext("2d")?.drawImage(bitmap, 0, 0);
  }, [bitmap]);
  return <canvas ref={canvasRef} className="absolute inset-0 h-full w-full" />;
}

interface PanelProps {
  index: number;
  edition: PreparedEdition;
  /** How open each panel's crease is, 0 folded to 1 flat; the front's never folds. */
  creases: MotionValue<number>[];
}

/** One slice of the edition, hinged on the bottom edge of the panel above and carrying the panels below. */
export function Panel({ index, edition, creases }: PanelProps) {
  const count = edition.panels.length;
  const isFirst = index === 0;
  const isLast = index === count - 1;
  const fold = useTransform(creases[index], (open) => 1 - open);
  const rotateX = useTransform(fold, (folded) => foldedAngle(index) * folded);
  const top = isFirst ? CORNER_RADIUS_PX : 0;
  const bottom = isLast ? CORNER_RADIUS_PX : 0;
  const overlap = isFirst ? 0 : SEAM_OVERLAP_PX;

  return (
    <m.div
      className="absolute inset-x-0"
      style={{
        top: isFirst ? 0 : "100%",
        // A nested panel's height is relative to the panel it hangs from.
        height: `${(isFirst ? edition.shares[0] : edition.shares[index] / edition.shares[index - 1]) * 100}%`,
        rotateX,
        transformOrigin: "50% 0%",
        transformStyle: "preserve-3d",
        willChange: isFirst ? "auto" : "transform",
      }}
    >
      <div
        className="absolute inset-x-0 bottom-0 overflow-hidden"
        style={{
          top: -overlap,
          backfaceVisibility: "hidden",
          borderRadius: `${top}px ${top}px ${bottom}px ${bottom}px`,
          background: edition.paper,
        }}
      >
        <div className="absolute inset-x-0 bottom-0" style={{ top: overlap }}>
          <PanelFace bitmap={edition.panels[index]} />
        </div>
        {!isFirst && (
          <CreaseShade fold={fold} isDarkPaper={edition.isDarkPaper} />
        )}
      </div>
      <div
        aria-hidden
        className="absolute inset-x-0 bottom-0"
        style={{
          top: -overlap,
          backfaceVisibility: "hidden",
          transform: "rotateX(180deg)",
          background: panelBack(edition.paper),
        }}
      />
      {!isLast && (
        <Panel index={index + 1} edition={edition} creases={creases} />
      )}
    </m.div>
  );
}
