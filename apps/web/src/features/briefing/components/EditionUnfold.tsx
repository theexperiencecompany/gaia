"use client";

import {
  animate,
  type MotionValue,
  useMotionValue,
  usePresence,
  useReducedMotion,
  useTransform,
} from "motion/react";
import * as m from "motion/react-m";
import { useEffect, useLayoutEffect, useRef, useState } from "react";

import {
  LETTER_PERSPECTIVE_PX,
  LETTER_TILT_DEG,
  type PreparedEdition,
  paperBackGradient,
} from "../utils/preparedEdition";

/** A panel stops short of a flat 180deg fold so stacked panels never z-fight. */
const FOLDED_DEG = 177;

/** One spring drives the whole letter open, so every panel shares its rhythm. */
const FOLD_SPRING = { type: "spring", visualDuration: 0.6, bounce: 0 } as const;
/** Closing plays the opening backwards: slow where it settled, quick where it lifted off. */
const REFOLD = { duration: 0.45, ease: [0.4, 0, 0.7, 0.2] } as const;
const REDUCED_FADE = { duration: 0.2, ease: "easeOut" } as const;
/** The letter lifts off the page over the first stretch of the spring, before the creases open. */
const LIFT_END = 0.22;
/** A letter opened from the chat travels from where it lay over this stretch. */
const TRAVEL_END = 0.7;
const FIRST_CREASE_START = 0.08;
/** Each crease opens over this share of the spring; the next starts long before it ends. */
const CREASE_SPAN = 0.55;
const CORNER_RADIUS_PX = 8;
/** The page behind frosts fully by the time the first crease is open, and clears as it refolds. */
const FROST_FULL = 0.5;

/** Accordion fold: each crease bends the opposite way to the one above it. */
function foldedAngle(index: number): number {
  return index % 2 === 1 ? -FOLDED_DEG : FOLDED_DEG;
}

/** How much of a stretch ending at `end` is still left at progress p, 1 at the start down to 0. */
function remaining(p: number, end: number): number {
  return Math.max(0, 1 - p / end);
}

/** Where crease index (1-based) starts opening on the shared 0..1 progress. */
function creaseStart(index: number, count: number): number {
  const creases = count - 1;
  const lastStart = 1 - CREASE_SPAN;
  const spread =
    creases > 1 ? (lastStart - FIRST_CREASE_START) / (creases - 1) : 0;
  return FIRST_CREASE_START + (index - 1) * spread;
}

function Crease({ fold }: { fold: MotionValue<number> }) {
  const shadow = useTransform(fold, [0, 1], [0, 0.55]);
  const valley = useTransform(fold, [0, 1], [0.05, 0.9]);
  return (
    <>
      <m.div
        aria-hidden
        className="pointer-events-none absolute inset-0 bg-black"
        style={{ opacity: shadow }}
      />
      <m.div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 h-10 bg-gradient-to-b from-black/45 via-black/10 to-transparent"
        style={{ opacity: valley }}
      />
      <m.div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 h-px bg-white/70 mix-blend-overlay"
        style={{ opacity: valley }}
      />
    </>
  );
}

/** A panel's slice, already cut at display resolution, drawn once into its own small canvas. */
export function PanelFace({ bitmap }: { bitmap: ImageBitmap }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  useLayoutEffect(() => {
    canvasRef.current?.getContext("2d")?.drawImage(bitmap, 0, 0);
  }, [bitmap]);
  return (
    <canvas
      ref={canvasRef}
      width={bitmap.width}
      height={bitmap.height}
      className="absolute inset-0 h-full w-full"
    />
  );
}

interface PanelProps {
  index: number;
  edition: PreparedEdition;
  progress: MotionValue<number>;
  isFlat: boolean;
  isMoving: boolean;
}

/** One slice of the edition, hinged on the bottom edge of the panel above and carrying the panels below. */
function Panel({ index, edition, progress, isFlat, isMoving }: PanelProps) {
  const count = edition.panels.length;
  const isFirst = index === 0;
  const isLast = index === count - 1;
  const start = creaseStart(index, count);
  const rotateX = useTransform(progress, (p) => {
    if (isFirst || isFlat) return 0;
    const opened = Math.min(1, Math.max(0, (p - start) / CREASE_SPAN));
    return foldedAngle(index) * (1 - opened);
  });
  const fold = useTransform(rotateX, (deg) => Math.abs(deg) / 180);
  const top = isFirst ? CORNER_RADIUS_PX : 0;
  const bottom = isLast ? CORNER_RADIUS_PX : 0;

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
        willChange: isMoving && !isFirst ? "transform" : "auto",
      }}
    >
      <div
        className="absolute inset-0 overflow-hidden"
        style={{
          backfaceVisibility: "hidden",
          borderRadius: `${top}px ${top}px ${bottom}px ${bottom}px`,
        }}
      >
        <PanelFace bitmap={edition.panels[index]} />
        {!isFirst && <Crease fold={fold} />}
      </div>
      <div
        aria-hidden
        className="absolute inset-0"
        style={{
          backfaceVisibility: "hidden",
          transform: "rotateX(180deg)",
          background: paperBackGradient(edition.paper),
        }}
      />
      {!isLast && (
        <Panel
          index={index + 1}
          edition={edition}
          progress={progress}
          isFlat={isFlat}
          isMoving={isMoving}
        />
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
 * The edition as a letter folded in panels. One spring takes it from folded to
 * open on mount and back the same way when the modal closes; creases overlap so
 * the letter opens as one motion. Reduced motion gets a fade.
 */
export function EditionUnfold({
  edition,
  alt,
  origin,
  onFolded,
}: EditionUnfoldProps) {
  const { aspect, width, panels } = edition;
  const reduceMotion = useReducedMotion() ?? false;
  const travels = Boolean(origin) && !reduceMotion;
  const [isPresent, safeToRemove] = usePresence();
  const [isMoving, setIsMoving] = useState(true);
  const progress = useMotionValue(0);
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
    letter.style.transform = `perspective(${LETTER_PERSPECTIVE_PX}px) translateX(${fromX.get()}px) translateY(${fromY.get()}px) scale(${fromScale.get()}) rotateX(${LETTER_TILT_DEG}deg)`;
    setIsPlaced(true);
  }, [travels, origin, fromX, fromY, fromScale]);

  useEffect(() => {
    setIsMoving(true);
    const controls = animate(
      progress,
      isPresent ? 1 : 0,
      reduceMotion ? REDUCED_FADE : isPresent ? FOLD_SPRING : REFOLD,
    );
    controls.then(() => {
      setIsMoving(false);
      if (isPresent) return;
      onFolded?.();
      safeToRemove();
    });
    return () => controls.stop();
  }, [isPresent, progress, reduceMotion, safeToRemove, onFolded]);

  const lift = reduceMotion ? 1 : LIFT_END;
  const fadeIn = useTransform(progress, [0, lift / 2], [0, 1]);
  const opacity = travels ? Number(isPlaced) : fadeIn;
  const x = useTransform(progress, (p) =>
    travels ? fromX.get() * remaining(p, TRAVEL_END) : 0,
  );
  const y = useTransform(progress, (p) => {
    if (travels) return fromY.get() * remaining(p, TRAVEL_END);
    return reduceMotion ? 0 : 14 * remaining(p, lift);
  });
  const scale = useTransform(progress, (p) => {
    if (travels) return 1 + (fromScale.get() - 1) * remaining(p, TRAVEL_END);
    return reduceMotion ? 1 : 1 - 0.03 * remaining(p, lift);
  });
  const rotateX = useTransform(progress, (p) =>
    travels ? LETTER_TILT_DEG * remaining(p, TRAVEL_END) : 0,
  );
  const shadowScale = useTransform(progress, [0, 1], [1 / panels.length, 1]);
  const frost = useTransform(progress, [0, FROST_FULL], [0, 1]);

  return (
    <>
      <m.div
        aria-hidden
        className="pointer-events-none fixed inset-0 bg-zinc-950/15 backdrop-blur-[10px]"
        style={{ opacity: frost }}
      />
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
          transformPerspective: travels ? LETTER_PERSPECTIVE_PX : undefined,
          transformOrigin: travels ? "0 0" : "50% 50%",
          width,
          aspectRatio: `1 / ${aspect}`,
          willChange: isMoving ? "transform, opacity" : "auto",
        }}
      >
        <m.div
          aria-hidden
          className="absolute inset-0 origin-top rounded-xl shadow-[0_40px_90px_-28px_rgba(0,0,0,0.8),0_14px_30px_-14px_rgba(0,0,0,0.55)]"
          style={{ scaleY: reduceMotion ? 1 : shadowScale }}
        />
        <div
          className="absolute inset-0"
          style={{ perspective: 1800, perspectiveOrigin: "50% 0%" }}
        >
          <Panel
            index={0}
            edition={edition}
            progress={progress}
            isFlat={reduceMotion}
            isMoving={isMoving}
          />
        </div>
      </m.div>
    </>
  );
}
