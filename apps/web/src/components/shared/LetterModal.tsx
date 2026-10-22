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
const LETTER_MOTION = {
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

interface LetterModalProps {
  isOpen: boolean;
  onClose: () => void;
  ariaLabel: string;
  /** The sheet itself; it brings its own surface and close control. */
  children: ReactNode;
}

/**
 * A single sheet handed to the reader: blurred backdrop, no modal chrome, and a
 * tilt-in entrance. HeroUI owns focus trap, Escape, scroll lock and focus restore.
 */
export function LetterModal({
  isOpen,
  onClose,
  ariaLabel,
  children,
}: LetterModalProps) {
  const reduceMotion = useReducedMotion();
  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      hideCloseButton
      aria-label={ariaLabel}
      classNames={{
        backdrop: "bg-black/70 backdrop-blur-sm",
        wrapper: "items-center justify-center p-3 sm:p-6",
        base: "m-0 max-h-[min(92vh,860px)] w-full max-w-[620px] overflow-y-auto overscroll-contain bg-transparent shadow-none",
      }}
      motionProps={LETTER_MOTION[reduceMotion ? "reduced" : "full"]}
    >
      <ModalContent>{children}</ModalContent>
    </Modal>
  );
}
