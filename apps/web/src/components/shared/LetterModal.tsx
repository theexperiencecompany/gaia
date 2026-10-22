"use client";

import { Modal, ModalContent } from "@heroui/modal";
import { useReducedMotion } from "motion/react";
import type { ReactNode } from "react";

/**
 * The sheet tilts and settles onto the screen rather than fading in. HeroUI
 * animates between two variants, so the pose it enters from is the pose it
 * exits to; reduced motion gets a plain fade instead.
 */
const LETTER_EASE: [number, number, number, number] = [0.19, 1, 0.22, 1];
const SHEET_MOTION = {
  full: {
    variants: {
      enter: {
        opacity: 1,
        scale: 1,
        rotate: 0,
        y: 0,
        transition: { duration: 0.55, ease: LETTER_EASE },
      },
      exit: {
        opacity: 0,
        scale: 0.95,
        rotate: 1,
        y: 22,
        transition: { duration: 0.3, ease: LETTER_EASE },
      },
    },
  },
  reduced: {
    variants: {
      enter: { opacity: 1, transition: { duration: 0.15 } },
      exit: { opacity: 0, transition: { duration: 0.15 } },
    },
  },
};

/**
 * A floating letter animates itself: the wrapper only hands its enter/exit
 * labels down and stays mounted until the letter has finished leaving.
 */
const FLOATING_MOTION = {
  variants: {
    enter: { opacity: 1 },
    exit: { opacity: 1, transition: { when: "afterChildren" } },
  },
};

const PRESENTATIONS = {
  sheet: {
    backdrop: "opaque",
    scrollBehavior: "normal",
    classNames: {
      backdrop: "bg-black/70 backdrop-blur-sm",
      wrapper: "items-center justify-center p-3 sm:p-6",
      base: "m-0 max-h-[min(92vh,860px)] w-full max-w-[620px] overflow-y-auto overscroll-contain bg-transparent shadow-none",
    },
  },
  floating: {
    backdrop: "transparent",
    scrollBehavior: "outside",
    classNames: {
      wrapper: "no-scrollbar items-start justify-center px-3 py-8",
      base: "m-0 my-auto w-auto max-w-none overflow-visible bg-transparent shadow-none sm:my-auto",
    },
  },
} as const;

interface LetterModalProps {
  isOpen: boolean;
  onClose: () => void;
  ariaLabel: string;
  /**
   * "sheet" dims the page and tilts the sheet in; "floating" leaves the page as
   * it is and lets the children animate on the modal's enter/exit variants.
   */
  presentation?: keyof typeof PRESENTATIONS;
  /** The sheet itself; it brings its own surface and close control. */
  children: ReactNode;
}

/**
 * A single sheet handed to the reader with no modal chrome. HeroUI owns focus
 * trap, Escape, outside press, scroll lock and focus restore.
 */
export function LetterModal({
  isOpen,
  onClose,
  ariaLabel,
  presentation = "sheet",
  children,
}: LetterModalProps) {
  const reduceMotion = useReducedMotion();
  const { backdrop, scrollBehavior, classNames } = PRESENTATIONS[presentation];
  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      hideCloseButton
      aria-label={ariaLabel}
      backdrop={backdrop}
      scrollBehavior={scrollBehavior}
      classNames={classNames}
      motionProps={
        presentation === "floating"
          ? FLOATING_MOTION
          : SHEET_MOTION[reduceMotion ? "reduced" : "full"]
      }
    >
      <ModalContent>{children}</ModalContent>
    </Modal>
  );
}
