"use client";

import { Modal } from "@heroui/react";
import { Cancel01Icon } from "@icons";
import { AnimatePresence, useReducedMotion, type Variants } from "motion/react";
import * as m from "motion/react-m";
import type { ReactNode } from "react";

import { modalVariants } from "@/components/shared/controlVariants";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { cn } from "@/lib/utils";

/**
 * The sheet tilts and settles onto the screen rather than fading in. It enters
 * from the pose it exits to; reduced motion gets a plain fade instead.
 */
const LETTER_EASE: [number, number, number, number] = [0.19, 1, 0.22, 1];
const SHEET_VARIANTS: Record<"full" | "reduced", Variants> = {
  full: {
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
  reduced: {
    enter: { opacity: 1, transition: { duration: 0.15 } },
    exit: { opacity: 0, transition: { duration: 0.15 } },
  },
};

/**
 * A floating letter animates itself: the wrapper only hands its enter/exit
 * labels down and stays mounted until the letter has finished leaving.
 */
const FLOATING_VARIANTS: Variants = {
  enter: { opacity: 1 },
  exit: { opacity: 1, transition: { when: "afterChildren" } },
};

const SCRIM_VARIANTS: Variants = {
  enter: { opacity: 1, transition: { duration: 0.2 } },
  exit: { opacity: 0, transition: { duration: 0.15 } },
};

const PRESENTATIONS = {
  sheet: {
    scrim: "bg-black/70 backdrop-blur-sm",
    dialog:
      "max-h-[min(92vh,860px)] w-full max-w-[620px] overflow-y-auto overscroll-contain",
  },
  floating: { scrim: null, dialog: undefined },
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
  /** The sheet itself; it brings its own surface. */
  children: ReactNode;
}

/**
 * A single sheet handed to the reader, with one close button pinned to the
 * screen's corner so a letter taller than the screen still has a way out.
 * HeroUI owns focus trap, Escape, outside press, scroll lock and focus restore;
 * the letter stays mounted, still open, until its exit animation has run.
 */
export function LetterModal({
  isOpen,
  onClose,
  ariaLabel,
  presentation = "sheet",
  children,
}: LetterModalProps) {
  const reduceMotion = useReducedMotion();
  const { scrim, dialog } = PRESENTATIONS[presentation];
  const variants =
    presentation === "floating"
      ? FLOATING_VARIANTS
      : SHEET_VARIANTS[reduceMotion ? "reduced" : "full"];
  return (
    <AnimatePresence>
      {isOpen && (
        <Modal
          key="letter"
          isOpen
          onOpenChange={(nextOpen) => {
            if (!nextOpen) onClose();
          }}
        >
          <Modal.Backdrop
            variant="transparent"
            className={presentation === "floating" ? "no-scrollbar" : undefined}
          >
            {scrim && (
              <m.div
                aria-hidden
                initial="exit"
                animate="enter"
                exit="exit"
                variants={SCRIM_VARIANTS}
                className={cn("pointer-events-none fixed inset-0", scrim)}
              />
            )}
            <Modal.Container placement="center" scroll="outside">
              <Modal.Dialog
                aria-label={ariaLabel}
                className={modalVariants({
                  surface: "bare",
                  className: dialog,
                })}
              >
                <GaiaButton
                  isIconOnly
                  shape="pill"
                  variant="tertiary"
                  tone="bright"
                  aria-label="Close"
                  onPress={onClose}
                  className="fixed top-3 right-3 z-50 shadow-[0_6px_20px_-6px_rgba(0,0,0,0.6)]"
                >
                  <Cancel01Icon className="size-5" />
                </GaiaButton>
                <m.div
                  initial="exit"
                  animate="enter"
                  exit="exit"
                  variants={variants}
                >
                  {children}
                </m.div>
              </Modal.Dialog>
            </Modal.Container>
          </Modal.Backdrop>
        </Modal>
      )}
    </AnimatePresence>
  );
}
