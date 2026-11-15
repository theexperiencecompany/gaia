"use client";

import { Button } from "@heroui/button";
import { Modal, ModalContent } from "@heroui/modal";
import { Cancel01Icon } from "@icons";
import { useReducedMotion, type Variants } from "motion/react";
import * as m from "motion/react-m";
import { type ReactNode, useState } from "react";

/**
 * A letter opens unhurried and leaves quickly: an ease-out rise, a short
 * ease-in exit that fades and shrinks it as one. Every letter surface and the
 * page behind it share these timings.
 */
export const LETTER_OPEN_TRANSITION = {
  duration: 0.4,
  ease: [0.33, 1, 0.68, 1],
} as const;
export const LETTER_CLOSE_TRANSITION = {
  duration: 0.2,
  ease: [0.4, 0, 1, 1],
} as const;
export const LETTER_REDUCED_TRANSITION = {
  duration: 0.15,
  ease: "easeOut",
} as const;
/** How far a letter shrinks as it leaves; opacity and scale run on the one curve. */
export const LETTER_EXIT_SCALE = 0.96;

/**
 * A sheet tilts and settles onto the screen, then leaves by fading and
 * shrinking in place. Reduced motion gets a plain fade both ways.
 */
export const LETTER_SHEET_VARIANTS: Record<"full" | "reduced", Variants> = {
  full: {
    arrive: { opacity: 0, scale: 0.95, rotate: 1, y: 22 },
    enter: {
      opacity: 1,
      scale: 1,
      rotate: 0,
      y: 0,
      transition: LETTER_OPEN_TRANSITION,
    },
    exit: {
      opacity: 0,
      scale: LETTER_EXIT_SCALE,
      transition: LETTER_CLOSE_TRANSITION,
    },
  },
  reduced: {
    arrive: { opacity: 0 },
    enter: { opacity: 1, transition: LETTER_REDUCED_TRANSITION },
    exit: { opacity: 0, transition: LETTER_REDUCED_TRANSITION },
  },
};

/** What the page behind a letter becomes: dimmed for a sheet, lightly frosted under a floating letter. */
const BACKDROP_LOOKS = {
  sheet: { blurPx: 8, tint: "rgba(0, 0, 0, 0.7)" },
  floating: { blurPx: 10, tint: "rgba(9, 9, 11, 0.15)" },
} as const;

type LetterPresentation = keyof typeof BACKDROP_LOOKS;

/**
 * The page frosts on the letter's own rise, on an even curve so the blur never
 * jumps ahead of the letter, and clears on its close. The blur radius and tint
 * ramp themselves rather than fading a finished blur in, which would cross a
 * sharp page with a blurred copy of it.
 */
const BACKDROP_OPEN_TRANSITION = {
  duration: LETTER_OPEN_TRANSITION.duration,
  ease: [0.25, 0.1, 0.25, 1],
} as const;

function backdropVariants(
  presentation: LetterPresentation,
  motion: "full" | "reduced",
): Variants {
  const { blurPx, tint } = BACKDROP_LOOKS[presentation];
  const clear = {
    backdropFilter: "blur(0px)",
    backgroundColor: "rgba(0, 0, 0, 0)",
  };
  return {
    arrive: clear,
    enter: {
      backdropFilter: `blur(${blurPx}px)`,
      backgroundColor: tint,
      transition:
        motion === "full"
          ? BACKDROP_OPEN_TRANSITION
          : LETTER_REDUCED_TRANSITION,
    },
    exit: {
      ...clear,
      transition:
        motion === "full" ? LETTER_CLOSE_TRANSITION : LETTER_REDUCED_TRANSITION,
    },
  };
}

/**
 * The letter animates itself: HeroUI's wrapper only stays mounted until the
 * letter has finished leaving.
 */
const WRAPPER_MOTION = {
  variants: {
    enter: { opacity: 1 },
    exit: { opacity: 1, transition: { when: "afterChildren" } },
  },
};

/**
 * Both presentations scroll the whole screen, so a letter taller than it is
 * never cut by a box of its own; the letter sets its own width.
 */
const MODAL_CLASS_NAMES = {
  wrapper: "no-scrollbar items-start justify-center px-3 py-8",
  base: "m-0 my-auto w-auto max-w-none overflow-visible bg-transparent shadow-none sm:my-auto",
} as const;

/** The close button's surface, for any control pinned beside it to match. */
export const LETTER_CONTROL_CLASSES =
  "bg-zinc-800 text-zinc-200 shadow-[0_6px_20px_-6px_rgba(0,0,0,0.6)] data-[hover=true]:bg-zinc-700";

interface LetterModalProps {
  isOpen: boolean;
  onClose: () => void;
  ariaLabel: string;
  /**
   * "sheet" dims the page and tilts the sheet in; "floating" frosts the page
   * lightly and lets the children animate themselves.
   */
  presentation?: LetterPresentation;
  /** Controls pinned beside the close button, reachable however far the letter scrolls. */
  actions?: ReactNode;
  /** The sheet itself; it brings its own surface. */
  children: ReactNode;
}

/**
 * A single sheet handed to the reader, with one close button pinned to the
 * screen's corner so a letter taller than the screen still has a way out.
 * HeroUI owns focus trap, Escape, outside press, scroll lock and focus restore.
 */
export function LetterModal({
  isOpen,
  onClose,
  ariaLabel,
  presentation = "sheet",
  actions,
  children,
}: LetterModalProps) {
  const motion = useReducedMotion() ? "reduced" : "full";
  // HeroUI attaches its motion asynchronously; a close before the entrance starts never runs
  // the exit and strands the modal open, so it stays mounted until then and closes after.
  const [isEntering, setIsEntering] = useState(isOpen);
  const [wasOpen, setWasOpen] = useState(isOpen);
  if (isOpen !== wasOpen) {
    setWasOpen(isOpen);
    if (isOpen) setIsEntering(true);
  }
  return (
    <Modal
      isOpen={isOpen || isEntering}
      onClose={onClose}
      hideCloseButton
      aria-label={ariaLabel}
      backdrop="transparent"
      scrollBehavior="outside"
      classNames={MODAL_CLASS_NAMES}
      motionProps={{
        ...WRAPPER_MOTION,
        onAnimationStart: () => setIsEntering(false),
      }}
    >
      <ModalContent>
        <m.div
          aria-hidden
          initial="arrive"
          animate="enter"
          exit="exit"
          variants={backdropVariants(presentation, motion)}
          className="pointer-events-none fixed inset-0"
        />
        <div className="fixed top-3 right-3 z-50 flex items-center gap-2">
          {actions}
          <Button
            isIconOnly
            radius="full"
            variant="flat"
            aria-label="Close"
            onPress={onClose}
            className={LETTER_CONTROL_CLASSES}
          >
            <Cancel01Icon className="size-5" />
          </Button>
        </div>
        {presentation === "sheet" ? (
          <m.div
            initial="arrive"
            animate="enter"
            exit="exit"
            variants={LETTER_SHEET_VARIANTS[motion]}
            className="relative"
          >
            {children}
          </m.div>
        ) : (
          children
        )}
      </ModalContent>
    </Modal>
  );
}
