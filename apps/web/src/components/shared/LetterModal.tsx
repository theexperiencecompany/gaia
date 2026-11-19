"use client";

import { Modal } from "@heroui/react";
import { Cancel01Icon } from "@icons";
import { AnimatePresence, useReducedMotion, type Variants } from "motion/react";
import * as m from "motion/react-m";
import type { ReactNode } from "react";

import { modalVariants } from "@/components/shared/controlVariants";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { LETTER_CONTROL_PROPS } from "@/components/shared/letterControlProps";
import {
  LETTER_CLOSE_TRANSITION,
  LETTER_OPEN_TRANSITION,
  LETTER_REDUCED_TRANSITION,
  LETTER_SHEET_VARIANTS,
} from "@/components/shared/letterMotion";

/** What the page behind a letter becomes: dimmed for a sheet, lightly frosted under a floating letter. */
const BACKDROP_LOOKS = {
  sheet: { blurPx: 8, tint: "rgba(0, 0, 0, 0.7)" },
  floating: { blurPx: 10, tint: "rgba(9, 9, 11, 0.15)" },
} as const;

type LetterPresentation = keyof typeof BACKDROP_LOOKS;

/**
 * The page frosts on the letter's own ease-out rise and clears on its ease-in
 * close. Blur radius and tint ramp from clear rather than fading a finished
 * blur in, which would cross a sharp page with a blurred copy of it.
 */
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
        motion === "full" ? LETTER_OPEN_TRANSITION : LETTER_REDUCED_TRANSITION,
    },
    exit: {
      ...clear,
      transition:
        motion === "full" ? LETTER_CLOSE_TRANSITION : LETTER_REDUCED_TRANSITION,
    },
  };
}

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
 * HeroUI owns focus trap, Escape, outside press, scroll lock and focus restore;
 * the letter stays mounted, still open, until it and the page behind it have
 * finished leaving. The whole screen scrolls, so a tall letter is never cut.
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
            className={modalVariants({
              surface: "bare",
              className: "no-scrollbar",
            })}
          >
            <m.div
              aria-hidden
              initial="arrive"
              animate="enter"
              exit="exit"
              variants={backdropVariants(presentation, motion)}
              className="pointer-events-none fixed inset-0"
            />
            <Modal.Container
              placement="center"
              scroll="outside"
              className={modalVariants({ surface: "bare" })}
            >
              <Modal.Dialog
                aria-label={ariaLabel}
                className={modalVariants({ surface: "bare" })}
              >
                <div className="fixed top-3 right-3 z-50 flex items-center gap-2">
                  {actions}
                  <GaiaButton
                    {...LETTER_CONTROL_PROPS}
                    isIconOnly
                    aria-label="Close"
                    onPress={onClose}
                  >
                    <Cancel01Icon className="size-5" />
                  </GaiaButton>
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
              </Modal.Dialog>
            </Modal.Container>
          </Modal.Backdrop>
        </Modal>
      )}
    </AnimatePresence>
  );
}
