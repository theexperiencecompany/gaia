"use client";

import {
  animate,
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
import {
  BRIEF_LETTER_WIDTH,
  LETTER_FOLD_PERSPECTIVE_PX,
  LETTER_TILT_DEG,
  LETTER_TILT_PERSPECTIVE_PX,
} from "../letterTokens";
import type { PreparedEdition } from "../utils/preparedEdition";
import { CORNER_RADIUS_PX, Panel, PanelFace } from "./LetterPanel";

/** How far a letter opened from a card rises as it arrives. */
const LIFT_PX = 12;
const LIFT_FROM_SCALE = 0.97;
/** A letter rising from a card is fully shown by this share of its rise. */
const FADE_IN_END = 0.6;

/** The first crease starts once the letter has begun to rise; a travelling one waits a little longer. */
const FIRST_CREASE_DELAY_S = { lift: 0.1, travel: 0.14 } as const;
/** The later creases start within this span of the first, however many there are. */
const CREASE_STAGGER_SPAN_S = 0.14;

/** When crease `index` (0-based, top down) starts opening, in seconds. */
function creaseDelay(index: number, creases: number, travels: boolean): number {
  const step = creases > 1 ? CREASE_STAGGER_SPAN_S / (creases - 1) : 0;
  return FIRST_CREASE_DELAY_S[travels ? "travel" : "lift"] + index * step;
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
