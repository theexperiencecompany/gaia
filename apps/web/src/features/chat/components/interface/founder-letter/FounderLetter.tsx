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

import {
  ACCENT,
  BODY_FONT,
  CODE_FONT,
  DISCOUNT_APPLIES,
  DISCOUNT_CODE,
  DISCOUNT_PERCENT,
  HANDWRITTEN_NOTE,
  INK,
  INK_SOFT,
  LETTER_DATE,
  LETTER_OPENED_KEY,
  LETTER_PARAGRAPHS,
  MARK_FONT,
  MEETING_CTA,
  MEETING_MAILTO,
  MEETING_SENTENCE,
  SALUTATION,
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
  "--letter-body": "clamp(14px, 1.65vh, 16px)",
  "--letter-body-lh": "1.68",
  "--letter-salutation": "clamp(17px, 2.3vh, 22px)",
  "--letter-small": "clamp(12px, 1.5vh, 13.5px)",
  "--letter-code": "clamp(17px, 2.4vh, 22px)",
  "--letter-pad-x": "clamp(20px, 6vw, 44px)",
  "--letter-pad-t": "clamp(12px, 3.2vh, 26px)",
  "--letter-pad-b": "clamp(44px, 7vh, 60px)",
} as CSSProperties;

/**
 * The paper is drawn in SVG: a warm golden gradient base, a vignette and a
 * grain layer, all passed through one feTurbulence + feDisplacementMap filter
 * so every edge gets the same organic torn/deckle silhouette. The CSS
 * drop-shadow follows that silhouette (box-shadow would stay rectangular).
 */
const PAPER_TORN_ID = "founder-letter-torn";
const PAPER_GRADIENT_ID = "founder-letter-paper";
const PAPER_VIGNETTE_ID = "founder-letter-vignette";

function PaperBackdrop() {
  return (
    <svg
      aria-hidden
      className="pointer-events-none absolute inset-0 h-full w-full"
      viewBox="0 0 600 800"
      preserveAspectRatio="none"
      style={{ filter: "drop-shadow(0 26px 60px rgba(0,0,0,0.5))" }}
    >
      <title>Decorative paper texture</title>
      <defs>
        <linearGradient id={PAPER_GRADIENT_ID} x1="0" y1="0" x2="0.55" y2="1">
          <stop offset="0" stopColor="#fff9ea" />
          <stop offset="0.45" stopColor="#f9ecca" />
          <stop offset="0.8" stopColor="#f4e0b4" />
          <stop offset="1" stopColor="#eed49e" />
        </linearGradient>
        <radialGradient id={PAPER_VIGNETTE_ID} cx="0.5" cy="0.32" r="0.95">
          <stop offset="0.5" stopColor="#a5711f" stopOpacity="0" />
          <stop offset="1" stopColor="#a5711f" stopOpacity="0.2" />
        </radialGradient>
        <filter id={PAPER_TORN_ID} x="-4%" y="-4%" width="108%" height="108%">
          <feTurbulence
            type="fractalNoise"
            baseFrequency="0.9"
            numOctaves="2"
            seed="3"
            result="grainTex"
          />
          <feColorMatrix
            in="grainTex"
            type="matrix"
            values="0 0 0 0 0.4  0 0 0 0 0.3  0 0 0 0 0.15  0 0 0 0.5 0"
            result="grain"
          />
          <feTurbulence
            type="fractalNoise"
            baseFrequency="0.055"
            numOctaves="2"
            seed="7"
            result="tear"
          />
          <feDisplacementMap in="grain" in2="tear" scale="5" />
        </filter>
        <linearGradient id="founder-letter-crease" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#a5711f" stopOpacity="0.22" />
          <stop offset="1" stopColor="#a5711f" stopOpacity="0" />
        </linearGradient>
      </defs>
      {/* Base paper */}
      <rect
        width="600"
        height="800"
        fill={`url(#${PAPER_GRADIENT_ID})`}
        filter={`url(#${PAPER_TORN_ID})`}
      />
      {/* Aged vignette */}
      <rect
        width="600"
        height="800"
        fill={`url(#${PAPER_VIGNETTE_ID})`}
        filter={`url(#${PAPER_TORN_ID})`}
      />
      {/* Grain */}
      <rect
        width="600"
        height="800"
        opacity="0.1"
        filter={`url(#${PAPER_TORN_ID})`}
        style={{ mixBlendMode: "multiply" }}
      />
      {/* Fold crease near the top, like a tri-folded letter */}
      <rect
        x="0"
        y="0"
        width="600"
        height="14"
        fill="url(#founder-letter-crease)"
        filter={`url(#${PAPER_TORN_ID})`}
      />
      {/* Two faint stains; real paper has a life of its own */}
      <circle
        cx="64"
        cy="250"
        r="90"
        fill="#c98a2e"
        opacity="0.07"
        style={{ filter: "blur(14px)" }}
      />
      <circle
        cx="548"
        cy="560"
        r="80"
        fill="#c98a2e"
        opacity="0.06"
        style={{ filter: "blur(12px)" }}
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
  const openPricingModal = usePricingModalStore((s) => s.openModal);
  const reduceMotion = useReducedMotion();
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const openButtonRef = useRef<HTMLButtonElement>(null);

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
        {/* The letter: a warm slip, folded once, sealed with wax. */}
        <span
          className="relative block h-10 w-14 rotate-[-3deg] rounded-[2px] shadow-[0_10px_24px_-6px_rgba(0,0,0,0.55)]"
          style={{
            background:
              "linear-gradient(145deg, #fff9ea 0%, #f7e9c6 55%, #efd9a8 100%)",
          }}
        >
          {/* Second page peeking out behind */}
          <span
            aria-hidden
            className="absolute -right-0.5 -bottom-0.5 -z-10 block h-10 w-14 rounded-[2px]"
            style={{
              background: "linear-gradient(145deg, #eed49e 0%, #e2c184 100%)",
            }}
          />
          {/* Folded flap */}
          <span
            aria-hidden
            className="absolute inset-x-0 top-0 h-3 rounded-t-[2px]"
            style={{
              background: "linear-gradient(180deg, #f2dcae 0%, #f9ecca 100%)",
            }}
          />
          {/* The fold crease */}
          <span
            aria-hidden
            className="absolute inset-x-0 top-3 h-px"
            style={{
              background:
                "linear-gradient(90deg, transparent, rgba(165,113,31,0.45) 30%, rgba(165,113,31,0.45) 70%, transparent)",
            }}
          />
          {/* Wax dot */}
          <span
            aria-hidden
            className="absolute -right-1 -bottom-1 h-3.5 w-3.5 rounded-full shadow-[0_2px_6px_rgba(80,20,10,0.55)]"
            style={{
              background:
                "radial-gradient(circle at 35% 30%, #f2564a 0%, #c22a1e 55%, #8f140c 100%)",
            }}
          />
        </span>
        {/* Attention ring until the letter has been opened once */}
        {pulse && (
          <span
            aria-hidden
            className="absolute inset-0 -z-10 animate-ping rounded-md bg-[#f6efdc]/50"
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
                className="absolute top-3 right-3 z-10 flex h-8 w-8 cursor-pointer items-center justify-center rounded-full outline-none transition-colors hover:bg-[#eed49e]/70 focus-visible:ring-2 focus-visible:ring-[#e2533f]"
              >
                <CancelIcon className="h-4 w-4" style={{ color: INK_SOFT }} />
              </button>

              {/* Letter content */}
              <div
                className="relative px-[var(--letter-pad-x)] pt-[var(--letter-pad-t)] pb-[var(--letter-pad-b)]"
                style={{ fontFamily: BODY_FONT }}
              >
                {/* Letterhead row: the mark and the date */}
                <div className="flex items-baseline justify-between">
                  <span
                    className="italic"
                    style={{
                      color: ACCENT,
                      fontFamily: MARK_FONT,
                      fontSize: "calc(var(--letter-body) * 1.35)",
                    }}
                  >
                    GAIA
                  </span>
                  <span
                    className="font-light"
                    style={{ color: INK_SOFT, fontSize: "var(--letter-small)" }}
                  >
                    {LETTER_DATE}
                  </span>
                </div>
                <div
                  className="mt-2 h-px w-full"
                  style={{
                    background: `linear-gradient(90deg, transparent, ${ACCENT} 25%, ${ACCENT} 75%, transparent)`,
                  }}
                />

                {/* Salutation */}
                <p
                  className="mt-3 italic"
                  style={{ color: INK, fontSize: "var(--letter-salutation)" }}
                >
                  {SALUTATION}
                </p>

                {/* Body */}
                <div
                  className="mt-2.5 space-y-2.5"
                  style={{
                    color: INK,
                    fontSize: "var(--letter-body)",
                    lineHeight: "var(--letter-body-lh)",
                  }}
                >
                  {LETTER_PARAGRAPHS.map((paragraph, i) => (
                    // biome-ignore lint/suspicious/noArrayIndexKey: static copy, order never changes
                    <p key={i}>{paragraph}</p>
                  ))}
                </div>

                {/* The offer, on its own vibrant slip of paper */}
                <div
                  className="mt-4 flex flex-wrap items-center justify-between gap-x-4 gap-y-2 rounded-sm px-4 py-2.5"
                  style={{
                    background:
                      "linear-gradient(115deg, #f97316 0%, #ef4444 55%, #e11d48 100%)",
                    boxShadow: "0 8px 24px -10px rgba(225, 29, 72, 0.55)",
                  }}
                >
                  <div>
                    <p
                      className="font-light"
                      style={{
                        color: "rgba(255, 248, 234, 0.92)",
                        fontSize: "var(--letter-small)",
                      }}
                    >
                      {DISCOUNT_PERCENT}% off your first year, on{" "}
                      {DISCOUNT_APPLIES}
                    </p>
                    <p
                      className="mt-0.5 font-bold tracking-tight"
                      style={{
                        color: "#fff8ea",
                        fontSize: "var(--letter-code)",
                        fontFamily: CODE_FONT,
                      }}
                    >
                      {DISCOUNT_CODE}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={copyCode}
                      className="flex h-8 w-8 cursor-pointer items-center justify-center rounded-full outline-none transition-all hover:bg-white/25 focus-visible:ring-2 focus-visible:ring-white/80 active:scale-90"
                      aria-label="Copy the discount code"
                      title={copied ? "Copied" : "Copy code"}
                    >
                      <Copy01Icon
                        className="h-3.5 w-3.5"
                        style={{ color: "#fff8ea" }}
                      />
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        openPricingModal();
                        closeLetter();
                      }}
                      className="flex h-8 cursor-pointer items-center gap-1.5 rounded-full px-3.5 text-[calc(var(--letter-small)*1.05)] font-semibold outline-none transition-all hover:opacity-90 focus-visible:ring-2 focus-visible:ring-white/80 active:scale-95"
                      style={{ background: "#fff8ea", color: "#e11d48" }}
                    >
                      Get the discount
                      <ArrowRightIcon
                        className="h-3.5 w-3.5"
                        style={{ color: "#e11d48" }}
                      />
                    </button>
                  </div>
                </div>

                {/* Meeting */}
                <p
                  className="mt-4"
                  style={{
                    color: INK,
                    fontSize: "var(--letter-body)",
                    lineHeight: "var(--letter-body-lh)",
                  }}
                >
                  {MEETING_SENTENCE}
                </p>
                <a
                  href={MEETING_MAILTO}
                  className="mt-1 inline-flex items-center gap-1.5 text-[calc(var(--letter-small)*1.05)] font-semibold underline decoration-[1.5px] underline-offset-4 outline-none transition-opacity hover:opacity-70 focus-visible:ring-2 focus-visible:ring-[#e2533f]"
                  style={{ color: ACCENT }}
                >
                  {MEETING_CTA}
                  <ArrowRightIcon
                    className="h-3 w-3"
                    style={{ color: ACCENT }}
                  />
                </a>

                {/* A quiet closing note */}
                <p
                  className="mt-5 font-light italic leading-relaxed"
                  style={{ color: INK_SOFT, fontSize: "var(--letter-small)" }}
                >
                  {HANDWRITTEN_NOTE}
                </p>

                {/* Signature: draws itself in, stroke by stroke */}
                <div className="mt-1.5 flex justify-end">
                  <Signature
                    active={isOpen}
                    scale="clamp(1.05, 0.14vh, 1.35)"
                  />
                </div>
                <p
                  className="mt-1 text-right font-light"
                  style={{ color: INK_SOFT, fontSize: "var(--letter-small)" }}
                >
                  {SIGNATURE_CAPTION}
                </p>

                {/* Folded corner: the seal rests on it */}
                <div
                  aria-hidden
                  className="absolute right-0 bottom-0 h-10 w-10"
                  style={{
                    background:
                      "linear-gradient(315deg, #e6c98e 0%, #f6e6bd 100%)",
                    clipPath: "polygon(100% 0, 100% 100%, 0 100%)",
                  }}
                />

                {/* Wax seal */}
                <div
                  aria-hidden
                  className="absolute right-2 bottom-2 flex h-14 w-14 rotate-[-10deg] items-center justify-center"
                  style={{
                    background:
                      "radial-gradient(circle at 34% 28%, #f2564a 0%, #c22a1e 55%, #8f140c 100%)",
                    borderRadius: "46% 54% 52% 48% / 52% 46% 55% 45%",
                    boxShadow:
                      "0 8px 18px -4px rgba(60,16,8,0.55), inset 0 -3px 8px rgba(40,8,4,0.5), inset 0 3px 6px rgba(255,190,170,0.35)",
                  }}
                >
                  <span
                    className="flex h-9 w-9 items-center justify-center rounded-full border"
                    style={{
                      borderColor: "rgba(255, 218, 200, 0.6)",
                      boxShadow: "inset 0 1px 4px rgba(255,218,200,0.4)",
                    }}
                  >
                    <span
                      className="italic"
                      style={{
                        color: "#ffd9c8",
                        fontFamily: MARK_FONT,
                        fontSize: "17px",
                      }}
                    >
                      G
                    </span>
                  </span>
                </div>
              </div>
            </m.div>
          </m.div>
        )}
      </AnimatePresence>
    </>
  );
}
