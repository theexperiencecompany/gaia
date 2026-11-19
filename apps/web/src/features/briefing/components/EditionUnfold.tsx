"use client";

import {
  animate,
  type MotionValue,
  motionValue,
  useMotionValue,
  usePresence,
  useReducedMotion,
  useTransform,
} from "motion/react";
import * as m from "motion/react-m";
import { useEffect, useLayoutEffect, useRef, useState } from "react";

import {
  LETTER_CLOSE_TRANSITION,
  LETTER_CREASE_TRANSITION,
  LETTER_EXIT_SCALE,
  LETTER_OPEN_TRANSITION,
  LETTER_REDUCED_TRANSITION,
  LETTER_TRAVEL_TRANSITION,
} from "@/components/shared/letterMotion";
import { cn } from "@/lib/utils";
import {
  BRIEF_LETTER_WIDTH,
  LETTER_FOLD_PERSPECTIVE_PX,
  LETTER_TILT_DEG,
  LETTER_TILT_PERSPECTIVE_PX,
} from "../letterTokens";
import { panelBack } from "../paperMaterial";
import type { PreparedEdition } from "../utils/preparedEdition";

/** A panel stops short of a flat 180deg fold so stacked panels never z-fight. */
const FOLDED_DEG = 177;
const CORNER_RADIUS_PX = 8;
/** Each lower panel reaches this far up under the one above, so no hairline of page shows at the crease. */
const SEAM_OVERLAP_PX = 1;
/** How far a letter opened from a card rises as it arrives. */
const LIFT_PX = 12;
const LIFT_FROM_SCALE = 0.97;
/** A letter rising from a card is fully shown by this share of its rise. */
const FADE_IN_END = 0.6;

/** The first crease starts once the letter has begun to rise; a travelling one waits a little longer. */
const FIRST_CREASE_DELAY_S = { lift: 0.1, travel: 0.14 } as const;
/** The later creases start within this span of the first, however many there are. */
const CREASE_STAGGER_SPAN_S = 0.14;

/** Accordion fold: each crease bends the opposite way to the one above it. */
function foldedAngle(index: number): number {
  return index % 2 === 1 ? -FOLDED_DEG : FOLDED_DEG;
}

/** When crease `index` (0-based, top down) starts opening, in seconds. */
function creaseDelay(index: number, creases: number, travels: boolean): number {
  const step = creases > 1 ? CREASE_STAGGER_SPAN_S / (creases - 1) : 0;
  return FIRST_CREASE_DELAY_S[travels ? "travel" : "lift"] + index * step;
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
function Panel({ index, edition, creases }: PanelProps) {
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

export interface EditionUnfoldProps {
  edition: PreparedEdition;
  alt: string;
  /** Where the folded letter lay on the page; it travels from and back to there. */
  origin?: DOMRect | null;
  /** Called once the letter has folded back and left. */
  onFolded?: () => void;
}

/**
 * The edition as a letter folded in panels. It rises (or travels from where it
 * lay), then each crease opens on its own staggered ease so the letter unfolds
 * as one deliberate motion; once open it rests as the one whole sheet. Closing
 * fades and shrinks it where it lies. Reduced motion gets a plain fade.
 */
export function EditionUnfold({
  edition,
  alt,
  origin,
  onFolded,
}: EditionUnfoldProps) {
  const { aspect, panels, shares } = edition;
  const reduceMotion = useReducedMotion() ?? false;
  const travels = Boolean(origin) && !reduceMotion;
  const [isPresent, safeToRemove] = usePresence();
  const [isOpening, setIsOpening] = useState(!reduceMotion);
  /** 0 as the letter arrives, 1 once it has risen or travelled into place. */
  const enter = useMotionValue(0);
  /** 0 while the letter is open, 1 once it has left. */
  const leave = useMotionValue(0);
  const [creases] = useState(() =>
    panels.map((_, index) => motionValue(index === 0 ? 1 : 0)),
  );
  const letterRef = useRef<HTMLDivElement>(null);
  const fromX = useMotionValue(0);
  const fromY = useMotionValue(0);
  const fromScale = useMotionValue(1);
  // Hidden until the travel from where it lay has been measured and applied.
  const [isPlaced, setIsPlaced] = useState(!travels);

  // Measured before paint, while the letter still sits untransformed where it will open.
  useLayoutEffect(() => {
    const letter = letterRef.current;
    if (!travels || !origin || !letter) return;
    letter.style.transform = "none";
    const target = letter.getBoundingClientRect();
    fromX.set(origin.left - target.left);
    fromY.set(origin.top - target.top);
    fromScale.set(origin.width / target.width);
    // Motion applies the values on its next frame; paint the starting pose now so frame one is the letter in place.
    letter.style.transform = `perspective(${LETTER_TILT_PERSPECTIVE_PX}px) translateX(${fromX.get()}px) translateY(${fromY.get()}px) scale(${fromScale.get()}) rotateX(${LETTER_TILT_DEG}deg)`;
    setIsPlaced(true);
  }, [travels, origin, fromX, fromY, fromScale]);

  useEffect(() => {
    let isCurrent = true;
    if (isPresent) {
      const opening = reduceMotion
        ? [animate(enter, 1, LETTER_REDUCED_TRANSITION)]
        : [
            animate(
              enter,
              1,
              travels ? LETTER_TRAVEL_TRANSITION : LETTER_OPEN_TRANSITION,
            ),
            ...creases.slice(1).map((crease, index) =>
              animate(crease, 1, {
                ...LETTER_CREASE_TRANSITION,
                delay: creaseDelay(index, creases.length - 1, travels),
              }),
            ),
          ];
      void Promise.all(opening).then(() => {
        if (isCurrent) setIsOpening(false);
      });
      return () => {
        isCurrent = false;
        for (const animation of opening) animation.stop();
      };
    }
    // A close mid-opening leaves the creases where they are; the letter leaves as it stands.
    const leaving = animate(
      leave,
      1,
      reduceMotion ? LETTER_REDUCED_TRANSITION : LETTER_CLOSE_TRANSITION,
    );
    leaving.then(() => {
      if (!isCurrent) return;
      onFolded?.();
      safeToRemove();
    });
    return () => {
      isCurrent = false;
      leaving.stop();
    };
  }, [
    isPresent,
    enter,
    leave,
    creases,
    travels,
    reduceMotion,
    safeToRemove,
    onFolded,
  ]);

  const opacity = useTransform([enter, leave], ([shown, gone]: number[]) => {
    const arrived = travels
      ? Number(isPlaced)
      : Math.min(1, shown / FADE_IN_END);
    return arrived * (1 - gone);
  });
  const x = useTransform(enter, (e) => (travels ? fromX.get() * (1 - e) : 0));
  const y = useTransform(enter, (e) => {
    if (travels) return fromY.get() * (1 - e);
    return reduceMotion ? 0 : LIFT_PX * (1 - e);
  });
  const scale = useTransform([enter, leave], ([e, gone]: number[]) => {
    if (reduceMotion) return 1;
    const exit = 1 - (1 - LETTER_EXIT_SCALE) * gone;
    const from = travels ? fromScale.get() : LIFT_FROM_SCALE;
    return (from + (1 - from) * e) * exit;
  });
  const rotateX = useTransform(enter, (e) =>
    travels ? LETTER_TILT_DEG * (1 - e) : 0,
  );
  // The shadow covers what has unfolded so far, not the whole sheet.
  const shadowScale = useTransform(creases, (opens: number[]) =>
    opens.reduce((sum, open, index) => sum + shares[index] * open, 0),
  );
  const isMoving = isOpening || !isPresent;

  return (
    <m.div
      ref={letterRef}
      role="img"
      aria-label={alt}
      className="relative"
      style={{
        opacity,
        x,
        y,
        scale,
        rotateX,
        transformPerspective: travels ? LETTER_TILT_PERSPECTIVE_PX : undefined,
        // A settled letter shrinks about its centre; one still travelling keeps the corner it travels by.
        transformOrigin:
          travels && (isPresent || isOpening) ? "0 0" : "50% 50%",
        width: BRIEF_LETTER_WIDTH,
        aspectRatio: `1 / ${aspect}`,
        willChange: isMoving ? "transform, opacity" : "auto",
      }}
    >
      <m.div
        aria-hidden
        className="absolute inset-0 origin-top rounded-xl shadow-[0_40px_90px_-28px_rgba(0,0,0,0.8),0_14px_30px_-14px_rgba(0,0,0,0.55)]"
        style={{ scaleY: isOpening ? shadowScale : 1 }}
      />
      {isOpening ? (
        <div
          className="absolute inset-0"
          style={{
            perspective: LETTER_FOLD_PERSPECTIVE_PX,
            perspectiveOrigin: "50% 0%",
          }}
        >
          <Panel index={0} edition={edition} creases={creases} />
        </div>
      ) : (
        <div
          className="absolute inset-0 overflow-hidden"
          style={{ borderRadius: CORNER_RADIUS_PX }}
        >
          <PanelFace bitmap={edition.sheet} />
        </div>
      )}
    </m.div>
  );
}
