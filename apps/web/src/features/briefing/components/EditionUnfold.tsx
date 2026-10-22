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

import type { PreparedEdition } from "../utils/preparedEdition";

/** A panel stops short of a flat 180deg fold so stacked panels never z-fight. */
const FOLDED_DEG = 177;

/** One spring drives the whole letter open, so every panel shares its rhythm. */
const FOLD_SPRING = { type: "spring", visualDuration: 0.6, bounce: 0 } as const;
/** Closing plays the opening backwards: slow where it settled, quick where it lifted off. */
const REFOLD = { duration: 0.45, ease: [0.4, 0, 0.7, 0.2] } as const;
const REDUCED_FADE = { duration: 0.2, ease: "easeOut" } as const;
/** The letter lifts off the page over the first stretch of the spring, before the creases open. */
const LIFT_END = 0.22;
const FIRST_CREASE_START = 0.08;
/** Each crease opens over this share of the spring; the next starts long before it ends. */
const CREASE_SPAN = 0.55;
const CORNER_RADIUS_PX = 12;
/** The page behind frosts fully by the time the first crease is open, and clears as it refolds. */
const FROST_FULL = 0.5;

/** The back of the paper, seen while a panel is still folded behind the one above it. */
const PAPER_BACK =
  "linear-gradient(180deg, #a8a294 0%, #c4beb1 45%, #cbc5b8 100%)";

/** Accordion fold: each crease bends the opposite way to the one above it. */
function foldedAngle(index: number): number {
  return index % 2 === 1 ? -FOLDED_DEG : FOLDED_DEG;
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

/** The panel's slice, already cut at display resolution, drawn once into its own small canvas. */
function PanelFace({ bitmap }: { bitmap: ImageBitmap }) {
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
  panels: ImageBitmap[];
  progress: MotionValue<number>;
  isFlat: boolean;
  isMoving: boolean;
}

/** One slice of the edition, hinged on the bottom edge of the panel above and carrying the panels below. */
function Panel({ index, panels, progress, isFlat, isMoving }: PanelProps) {
  const count = panels.length;
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
        height: isFirst ? `${100 / count}%` : "100%",
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
        <PanelFace bitmap={panels[index]} />
        {!isFirst && <Crease fold={fold} />}
      </div>
      <div
        aria-hidden
        className="absolute inset-0"
        style={{
          backfaceVisibility: "hidden",
          transform: "rotateX(180deg)",
          background: PAPER_BACK,
        }}
      />
      {!isLast && (
        <Panel
          index={index + 1}
          panels={panels}
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
}

/**
 * The edition as a letter folded in panels. One spring takes it from folded to
 * open on mount and back the same way when the modal closes; creases overlap so
 * the letter opens as one motion. Reduced motion gets a fade.
 */
export function EditionUnfold({ edition, alt }: EditionUnfoldProps) {
  const { aspect, width, panels } = edition;
  const reduceMotion = useReducedMotion() ?? false;
  const [isPresent, safeToRemove] = usePresence();
  const [isMoving, setIsMoving] = useState(true);
  const progress = useMotionValue(0);

  useEffect(() => {
    setIsMoving(true);
    const controls = animate(
      progress,
      isPresent ? 1 : 0,
      reduceMotion ? REDUCED_FADE : isPresent ? FOLD_SPRING : REFOLD,
    );
    controls.then(() => {
      setIsMoving(false);
      if (!isPresent) safeToRemove();
    });
    return () => controls.stop();
  }, [isPresent, progress, reduceMotion, safeToRemove]);

  const lift = reduceMotion ? 1 : LIFT_END;
  const opacity = useTransform(progress, [0, lift / 2], [0, 1]);
  const y = useTransform(progress, [0, lift], [reduceMotion ? 0 : 14, 0]);
  const scale = useTransform(progress, [0, lift], [reduceMotion ? 1 : 0.97, 1]);
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
        role="img"
        aria-label={alt}
        className="relative"
        style={{
          opacity,
          y,
          scale,
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
            panels={panels}
            progress={progress}
            isFlat={reduceMotion}
            isMoving={isMoving}
          />
        </div>
      </m.div>
    </>
  );
}
