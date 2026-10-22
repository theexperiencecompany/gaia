"use client";

import {
  type MotionValue,
  useMotionValue,
  useReducedMotion,
  useTransform,
  type Variants,
} from "motion/react";
import * as m from "motion/react-m";

/** A panel stops short of a flat 180deg fold so stacked panels never z-fight. */
const FOLDED_DEG = 177;
/** One panel per ~0.75 of the width in height: a tall edition folds in four, a short one in three. */
const PANEL_ASPECT = 0.75;
const MIN_PANELS = 3;
const MAX_PANELS = 4;
const EDITION_MAX_WIDTH = 540;

const OPEN_STAGGER_S = 0.14;
const OPEN_SPRING = {
  type: "spring",
  visualDuration: 0.44,
  bounce: 0.16,
} as const;
const CLOSE_STAGGER_S = 0.07;
const CLOSE_SPRING = {
  type: "spring",
  visualDuration: 0.28,
  bounce: 0,
} as const;
/** A fold's last stretch happens behind the top panel, so the letter leaves once the visible part is done. */
const FOLD_VISIBLE_SHARE = 0.55;
const EASE_OUT: [number, number, number, number] = [0.23, 1, 0.32, 1];
const EASE_IN: [number, number, number, number] = [0.55, 0, 1, 0.45];

/** The back of the paper, seen while a panel is still folded behind the one above it. */
const PAPER_BACK =
  "linear-gradient(180deg, #a8a294 0%, #c4beb1 45%, #cbc5b8 100%)";

function panelCountFor(aspect: number): number {
  return Math.min(
    MAX_PANELS,
    Math.max(MIN_PANELS, Math.round(aspect / PANEL_ASPECT)),
  );
}

interface PanelProps {
  index: number;
  count: number;
  src: string;
}

/** Accordion fold: each crease bends the opposite way to the one above it. */
function foldedAngle(index: number): number {
  return index % 2 === 1 ? -FOLDED_DEG : FOLDED_DEG;
}

function panelVariants(index: number, count: number): Variants {
  return {
    enter: {
      rotateX: 0,
      transition: {
        ...OPEN_SPRING,
        delay: (index - 1) * OPEN_STAGGER_S,
      },
    },
    exit: {
      rotateX: foldedAngle(index),
      transition: {
        ...CLOSE_SPRING,
        delay: (count - 1 - index) * CLOSE_STAGGER_S,
      },
    },
  };
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

/** One slice of the edition, hinged on the bottom edge of the panel above and carrying the panels below. */
function Panel({ index, count, src }: PanelProps) {
  const isFirst = index === 0;
  const isLast = index === count - 1;
  const rotateX = useMotionValue(isFirst ? 0 : foldedAngle(index));
  const fold = useTransform(rotateX, (deg) => Math.abs(deg) / 180);

  return (
    <m.div
      variants={isFirst ? undefined : panelVariants(index, count)}
      className="absolute inset-x-0"
      style={{
        top: isFirst ? 0 : "100%",
        height: isFirst ? `${100 / count}%` : "100%",
        rotateX,
        transformOrigin: "50% 0%",
        transformStyle: "preserve-3d",
      }}
    >
      <div
        className="absolute inset-0 overflow-hidden"
        style={{
          backfaceVisibility: "hidden",
          backgroundImage: `url("${src}")`,
          backgroundSize: `100% ${count * 100}%`,
          backgroundPosition: `0 ${(index / (count - 1)) * 100}%`,
          borderTopLeftRadius: isFirst ? 12 : 0,
          borderTopRightRadius: isFirst ? 12 : 0,
          borderBottomLeftRadius: isLast ? 12 : 0,
          borderBottomRightRadius: isLast ? 12 : 0,
        }}
      >
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
      {!isLast && <Panel index={index + 1} count={count} src={src} />}
    </m.div>
  );
}

export interface EditionUnfoldProps {
  src: string;
  /** Natural height over width of the edition image. */
  aspect: number;
  alt: string;
}

/**
 * The edition as a letter folded in panels; it unfolds crease by crease on the
 * modal's enter variant and folds back up on exit. Reduced motion gets a fade.
 */
export function EditionUnfold({ src, aspect, alt }: EditionUnfoldProps) {
  const reduceMotion = useReducedMotion();
  const count = panelCountFor(aspect);
  const openTotal = (count - 2) * OPEN_STAGGER_S + OPEN_SPRING.visualDuration;
  const closeTotal =
    (count - 2) * CLOSE_STAGGER_S + CLOSE_SPRING.visualDuration;

  const letterVariants: Variants = reduceMotion
    ? {
        enter: { opacity: 1, transition: { duration: 0.2 } },
        exit: { opacity: 0, transition: { duration: 0.15 } },
      }
    : {
        enter: {
          opacity: 1,
          y: 0,
          scale: 1,
          transition: { duration: 0.32, ease: EASE_OUT },
        },
        exit: {
          opacity: 0,
          y: 12,
          scale: 0.97,
          transition: {
            duration: 0.2,
            ease: EASE_IN,
            delay: closeTotal * FOLD_VISIBLE_SHARE,
          },
        },
      };

  const shadowVariants: Variants = {
    enter: {
      scaleY: 1,
      opacity: 1,
      transition: { duration: openTotal, ease: EASE_OUT },
    },
    exit: {
      scaleY: 1 / count,
      opacity: 0.6,
      transition: { duration: closeTotal, ease: EASE_IN },
    },
  };

  return (
    <m.div
      role="img"
      aria-label={alt}
      variants={letterVariants}
      className="relative"
      style={{
        width: `min(${EDITION_MAX_WIDTH}px, calc(100vw - 24px))`,
        aspectRatio: `1 / ${aspect}`,
      }}
    >
      {reduceMotion ? (
        <div
          className="absolute inset-0 rounded-xl bg-cover shadow-[0_32px_80px_-24px_rgba(0,0,0,0.75)]"
          style={{ backgroundImage: `url("${src}")` }}
        />
      ) : (
        <>
          <m.div
            aria-hidden
            variants={shadowVariants}
            className="absolute inset-0 origin-top rounded-xl shadow-[0_40px_90px_-28px_rgba(0,0,0,0.8),0_14px_30px_-14px_rgba(0,0,0,0.55)]"
          />
          <div
            className="absolute inset-0"
            style={{ perspective: 1800, perspectiveOrigin: "50% 0%" }}
          >
            <Panel index={0} count={count} src={src} />
          </div>
        </>
      )}
    </m.div>
  );
}
