"use client";

import { ArrowRightIcon, CancelIcon, Copy01Icon } from "@icons";
import { AnimatePresence, useReducedMotion } from "motion/react";
import * as m from "motion/react-m";
import {
  type CSSProperties,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import { toast } from "@/lib/toast";
import { usePricingModalStore } from "@/stores/pricingModalStore";
import { useUserStore } from "@/stores/userStore";

import {
  BODY_FONT,
  DISCOUNT_APPLIES,
  DISCOUNT_CODE,
  DISCOUNT_PERCENT,
  INK,
  INK_SOFT,
  LETTER_OPENED_KEY,
  LETTER_PARAGRAPHS,
  MEETING_CTA,
  MEETING_MAILTO,
  MEETING_SENTENCE,
  SALUTATION_FALLBACK,
  SIGNATURE_CAPTION,
} from "./content";
import { Signature } from "./Signature";

/**
 * Typography and spacing scale with the viewport height (clamped), so the
 * whole letter fits without scrolling on any screen: on a short window the
 * letter compresses, on a tall one it breathes. Overflow scroll remains only
 * as a safety net for very short viewports.
 */
const LETTER_TYPOGRAPHY = {
  "--letter-body": "clamp(14px, 1.6vh, 15.5px)",
  "--letter-body-lh": "1.7",
  "--letter-salutation": "clamp(16px, 2.1vh, 20px)",
  "--letter-small": "clamp(12px, 1.45vh, 13px)",
  "--letter-code": "clamp(16px, 2.1vh, 19px)",
  "--letter-pad-x": "clamp(20px, 6vw, 46px)",
  "--letter-pad-t": "clamp(14px, 3.4vh, 28px)",
  "--letter-pad-b": "clamp(36px, 6vh, 52px)",
} as CSSProperties;

/** Flat golden paper (amber-300). One solid color, no gradient. */
const PAPER_GOLD = "#fcd34d";
/** Slightly deeper gold for the folded layers of the envelope button. */
const PAPER_GOLD_DEEP = "#fbbf24";

/**
 * The paper is a flat gold rect passed through a feTurbulence +
 * feDisplacementMap filter so the silhouette gets a subtle hand-torn deckle.
 * No grain, no gradient: gold paper, black ink.
 */
const PAPER_TORN_ID = "founder-letter-torn";

function PaperBackdrop() {
  return (
    <svg
      aria-hidden
      className="pointer-events-none absolute inset-0 h-full w-full"
      viewBox="0 0 600 800"
      preserveAspectRatio="none"
      style={{ filter: "drop-shadow(0 24px 50px rgba(0,0,0,0.4))" }}
    >
      <title>Decorative paper texture</title>
      <defs>
        <filter id={PAPER_TORN_ID} x="-4%" y="-4%" width="108%" height="108%">
          <feTurbulence
            type="fractalNoise"
            baseFrequency="0.06"
            numOctaves="2"
            seed="7"
            result="tear"
          />
          <feDisplacementMap in="SourceGraphic" in2="tear" scale="3" />
        </filter>
      </defs>
      <rect
        width="600"
        height="800"
        fill={PAPER_GOLD}
        filter={`url(#${PAPER_TORN_ID})`}
      />
    </svg>
  );
}

interface FounderLetterProps {
  /** Hidden during voice calls: the bottom-right corner belongs to voice controls. */
  hidden?: boolean;
}

export function FounderLetter({ hidden = false }: FounderLetterProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [pulse, setPulse] = useState(false);
  const [copied, setCopied] = useState(false);
  const userName = useUserStore((s) => s.name);
  const openPricingModal = usePricingModalStore((s) => s.openModal);
  const reduceMotion = useReducedMotion();
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const openButtonRef = useRef<HTMLButtonElement>(null);

  const firstName = userName.trim().split(" ")[0] || SALUTATION_FALLBACK;

  // Pulse the envelope until the letter has been opened once. Read in an
  // effect (not render) so server and client markup always match.
  useEffect(() => {
    setPulse(!window.localStorage.getItem(LETTER_OPENED_KEY));
  }, []);

  const openLetter = useCallback(() => {
    window.localStorage.setItem(LETTER_OPENED_KEY, "1");
    setPulse(false);
    setIsOpen(true);
  }, []);

  const closeLetter = useCallback(() => setIsOpen(false), []);

  // Escape closes; focus moves to the close button while open and back to the
  // envelope on close. Body scroll locks so the chat can't scroll under the letter.
  useEffect(() => {
    if (!isOpen) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeLetter();
    };
    document.addEventListener("keydown", onKeyDown);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeButtonRef.current?.focus();
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
      openButtonRef.current?.focus();
    };
  }, [isOpen, closeLetter]);

  const copyCode = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(DISCOUNT_CODE);
    } catch {
      // Clipboard API can be unavailable (permissions, non-secure context);
      // fall back to the legacy path so the code still reaches the user.
      const textarea = document.createElement("textarea");
      textarea.value = DISCOUNT_CODE;
      textarea.style.position = "fixed";
      textarea.style.opacity = "0";
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand("copy");
      textarea.remove();
    }
    setCopied(true);
    toast.success(`Code ${DISCOUNT_CODE} copied, it's yours`);
    window.setTimeout(() => setCopied(false), 2000);
  }, []);

  if (hidden) return null;

  return (
    <>
      {/* A folded letter, waiting in the bottom-right corner above the composer. */}
      <m.button
        ref={openButtonRef}
        type="button"
        onClick={openLetter}
        aria-label="A letter from Aryan Randeriya"
        title="A letter from Aryan"
        className="fixed right-4 bottom-24 z-40 isolate cursor-pointer rounded-md outline-none focus-visible:ring-2 focus-visible:ring-[#00bbff]"
        initial={false}
        whileHover={reduceMotion ? undefined : { y: -3, scale: 1.06 }}
        whileTap={reduceMotion ? undefined : { scale: 0.94 }}
        animate={reduceMotion ? undefined : { y: [0, -2, 0] }}
        transition={
          reduceMotion
            ? undefined
            : {
                y: {
                  duration: 3.4,
                  repeat: Number.POSITIVE_INFINITY,
                  ease: "easeInOut",
                },
              }
        }
      >
        {/* The letter: a flat gold slip, folded once. */}
        <span
          className="relative block h-10 w-14 rotate-[-3deg] rounded-[2px] shadow-[0_10px_24px_-6px_rgba(0,0,0,0.45)]"
          style={{ background: PAPER_GOLD }}
        >
          {/* Second page peeking out behind */}
          <span
            aria-hidden
            className="absolute -right-0.5 -bottom-0.5 -z-10 block h-10 w-14 rounded-[2px]"
            style={{ background: PAPER_GOLD_DEEP }}
          />
          {/* Folded flap */}
          <span
            aria-hidden
            className="absolute inset-x-0 top-0 h-3 rounded-t-[2px]"
            style={{ background: PAPER_GOLD_DEEP }}
          />
          {/* The fold crease */}
          <span
            aria-hidden
            className="absolute inset-x-0 top-3 h-px bg-black/20"
          />
        </span>
        {/* Attention ring until the letter has been opened once */}
        {pulse && (
          <span
            aria-hidden
            className="absolute inset-0 -z-10 animate-ping rounded-md bg-amber-200/50"
            style={{ animationDuration: "2.4s" }}
          />
        )}
      </m.button>

      <AnimatePresence>
        {isOpen && (
          <m.div
            role="dialog"
            aria-modal="true"
            aria-label="A letter from Aryan Randeriya"
            className="fixed inset-0 z-[70] flex items-center justify-center p-3 sm:p-6"
          >
            {/* The room dims, the letter glows */}
            <m.div
              className="absolute inset-0 bg-black/70 backdrop-blur-sm"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.25 }}
              onClick={closeLetter}
            />

            {/* The paper */}
            <m.div
              className="relative flex max-h-[min(92vh,860px)] w-full max-w-[600px] flex-col overflow-y-auto overscroll-contain outline-none"
              role="document"
              tabIndex={-1}
              style={LETTER_TYPOGRAPHY}
              initial={
                reduceMotion
                  ? { opacity: 0 }
                  : { opacity: 0, scale: 0.94, rotate: 1.1, y: 24 }
              }
              animate={
                reduceMotion
                  ? { opacity: 1 }
                  : { opacity: 1, scale: 1, rotate: 0, y: 0 }
              }
              exit={
                reduceMotion
                  ? { opacity: 0 }
                  : { opacity: 0, scale: 0.96, rotate: -0.6, y: 10 }
              }
              transition={{
                duration: reduceMotion ? 0.15 : 0.55,
                ease: [0.19, 1, 0.22, 1],
              }}
            >
              <PaperBackdrop />

              {/* Close */}
              <button
                ref={closeButtonRef}
                type="button"
                onClick={closeLetter}
                aria-label="Close the letter"
                className="absolute top-3 right-3 z-10 flex h-8 w-8 cursor-pointer items-center justify-center rounded-full outline-none transition-colors hover:bg-black/10 focus-visible:ring-2 focus-visible:ring-black/60"
              >
                <CancelIcon className="h-4 w-4" style={{ color: INK_SOFT }} />
              </button>

              {/* Letter content */}
              <div
                className="relative px-[var(--letter-pad-x)] pt-[var(--letter-pad-t)] pb-[var(--letter-pad-b)]"
                style={{ fontFamily: BODY_FONT, color: INK }}
              >
                {/* Salutation */}
                <p
                  className="font-semibold"
                  style={{ fontSize: "var(--letter-salutation)" }}
                >
                  Dear {firstName},
                </p>

                {/* Body */}
                <div
                  className="mt-2.5 space-y-2.5"
                  style={{
                    fontSize: "var(--letter-body)",
                    lineHeight: "var(--letter-body-lh)",
                  }}
                >
                  {LETTER_PARAGRAPHS.map((paragraph, i) => (
                    // biome-ignore lint/suspicious/noArrayIndexKey: static copy, order never changes
                    <p key={i}>{paragraph}</p>
                  ))}
                </div>

                {/* The offer, seamless and inline */}
                <div className="mt-3 space-y-2">
                  <p
                    style={{
                      fontSize: "var(--letter-body)",
                      lineHeight: "var(--letter-body-lh)",
                    }}
                  >
                    As a thank-you for believing in us when it wasn't easy, take{" "}
                    <strong className="font-bold">
                      {DISCOUNT_PERCENT}% off your first year
                    </strong>
                    , on {DISCOUNT_APPLIES}. Use{" "}
                    <strong className="font-bold">{DISCOUNT_CODE}</strong>
                    <button
                      type="button"
                      onClick={copyCode}
                      aria-label="Copy the discount code"
                      title={copied ? "Copied" : "Copy code"}
                      className="mx-1 inline-flex h-5 w-5 translate-y-[-1px] cursor-pointer items-center justify-center rounded-full align-middle outline-none transition-colors hover:bg-black/10 focus-visible:ring-2 focus-visible:ring-black/60 active:scale-90"
                    >
                      <Copy01Icon className="h-3 w-3" style={{ color: INK }} />
                    </button>
                    at checkout.
                  </p>
                  <button
                    type="button"
                    onClick={() => {
                      openPricingModal();
                      closeLetter();
                    }}
                    className="inline-flex h-7 cursor-pointer items-center gap-1 rounded-full bg-black px-3 text-[calc(var(--letter-small)*0.95)] font-semibold text-amber-300 outline-none transition-opacity hover:opacity-80 focus-visible:ring-2 focus-visible:ring-black/60 active:scale-95"
                  >
                    Get the discount
                    <ArrowRightIcon
                      className="h-3 w-3"
                      style={{ color: PAPER_GOLD }}
                    />
                  </button>
                </div>

                {/* Meeting */}
                <p
                  className="mt-4"
                  style={{
                    fontSize: "var(--letter-body)",
                    lineHeight: "var(--letter-body-lh)",
                  }}
                >
                  {MEETING_SENTENCE}
                </p>
                <a
                  href={MEETING_MAILTO}
                  className="mt-1 inline-flex items-center gap-1.5 text-[calc(var(--letter-small)*1.05)] font-semibold underline decoration-[1.5px] underline-offset-4 outline-none transition-opacity hover:opacity-70 focus-visible:ring-2 focus-visible:ring-black/60"
                >
                  {MEETING_CTA}
                  <ArrowRightIcon className="h-3 w-3" style={{ color: INK }} />
                </a>

                {/* Signature: draws itself in, stroke by stroke */}
                <div className="mt-6">
                  <Signature
                    active={isOpen}
                    scale="clamp(1.05, 0.14vh, 1.35)"
                  />
                </div>
                <p
                  className="mt-1 font-normal"
                  style={{ fontSize: "var(--letter-small)" }}
                >
                  {SIGNATURE_CAPTION}
                </p>
              </div>
            </m.div>
          </m.div>
        )}
      </AnimatePresence>
    </>
  );
}
