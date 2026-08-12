"use client";

import { ArrowRightIcon, CancelIcon, Copy01Icon, Tick02Icon } from "@icons";
import { AnimatePresence, useReducedMotion } from "motion/react";
import * as m from "motion/react-m";
import Image from "next/image";
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
  MEETING_SENTENCE,
  MEETING_URL,
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
  "--letter-pad-x": "clamp(24px, 6vw, 58px)",
  "--letter-pad-t": "clamp(14px, 3.4vh, 28px)",
  "--letter-pad-b": "clamp(36px, 6vh, 52px)",
} as CSSProperties;

/** Ivory stock with the faintest warmth, so the black ink stays the darkest
 * thing on the page. Used for the paper and for ink-on-paper reversals. */
const PAPER_CREAM = "#fdf8ea";

/** The sealed envelope the letter arrives in, at its intrinsic size. */
const ENVELOPE_IMAGE = "/images/icons/sealed-envelope.webp";
const ENVELOPE_WIDTH = 512;
const ENVELOPE_HEIGHT = 356;

/**
 * The paper: a sheet torn out by hand, ragged on all four edges.
 *
 * The tear is a displacement map, not a hand-plotted path. Fractal noise
 * pushes the edge of a plain rectangle in and out, which is what a real fibre
 * tear looks like and what a path of fake zigzags never does. The same noise
 * field, at a much finer frequency, is laid back over the sheet as grain, so
 * the texture and the edge come from one material.
 */
const PAPER_VB_W = 600;
const PAPER_VB_H = 800;
/** Room for the tear to bite into the rectangle without clipping. */
const TEAR_INSET = 12;
const TEAR_DEPTH = 15;

function PaperBackdrop() {
  return (
    <svg
      aria-hidden
      className="pointer-events-none absolute inset-0 h-full w-full"
      viewBox={`0 0 ${PAPER_VB_W} ${PAPER_VB_H}`}
      preserveAspectRatio="none"
      style={{ filter: "drop-shadow(0 26px 55px rgba(0,0,0,0.5))" }}
    >
      <title>Decorative letter paper</title>
      <defs>
        {/* Stationery: cool white where the light hits, warming into the
         * shadow at the bottom right, the way a real sheet sits on a desk. */}
        <linearGradient id="fl-paper" x1="0.05" y1="0" x2="0.85" y2="1">
          <stop offset="0%" stopColor="#fffefb" />
          <stop offset="35%" stopColor="#fdfaf1" />
          <stop offset="72%" stopColor="#f8f1e0" />
          <stop offset="100%" stopColor="#efe4cd" />
        </linearGradient>
        <radialGradient
          id="fl-paper-light"
          cx="0.18"
          cy="0.04"
          r="0.75"
          gradientUnits="objectBoundingBox"
        >
          <stop offset="0%" stopColor="#ffffff" stopOpacity="0.95" />
          <stop offset="100%" stopColor="#ffffff" stopOpacity="0" />
        </radialGradient>
        {/* The sheet lifts very slightly at the left and right edges. */}
        <linearGradient id="fl-paper-edges" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor="#a98c52" stopOpacity="0.14" />
          <stop offset="9%" stopColor="#a98c52" stopOpacity="0" />
          <stop offset="91%" stopColor="#a98c52" stopOpacity="0" />
          <stop offset="100%" stopColor="#a98c52" stopOpacity="0.14" />
        </linearGradient>

        {/* The tear: noise displacing the edge of the sheet. */}
        <filter
          id="fl-tear"
          x="-6%"
          y="-5%"
          width="112%"
          height="110%"
          filterUnits="objectBoundingBox"
        >
          <feTurbulence
            type="fractalNoise"
            baseFrequency="0.014 0.022"
            numOctaves="4"
            seed="11"
            result="tearNoise"
          />
          <feDisplacementMap
            in="SourceGraphic"
            in2="tearNoise"
            scale={TEAR_DEPTH}
            xChannelSelector="R"
            yChannelSelector="G"
          />
        </filter>

        {/* The grain: the same fibre, an order of magnitude finer. */}
        <filter id="fl-grain" x="0%" y="0%" width="100%" height="100%">
          <feTurbulence
            type="fractalNoise"
            baseFrequency="0.85"
            numOctaves="4"
            seed="11"
            result="grain"
          />
          <feColorMatrix in="grain" type="saturate" values="0" result="grey" />
          <feComponentTransfer in="grey">
            <feFuncA type="linear" slope="0.16" intercept="0" />
          </feComponentTransfer>
        </filter>

        {/* Mottling: where the stock is very slightly thicker or thinner. */}
        <filter id="fl-mottle" x="0%" y="0%" width="100%" height="100%">
          <feTurbulence
            type="fractalNoise"
            baseFrequency="0.006"
            numOctaves="3"
            seed="4"
            result="cloud"
          />
          <feColorMatrix in="cloud" type="saturate" values="0" result="grey" />
          <feComponentTransfer in="grey">
            <feFuncA type="linear" slope="0.1" intercept="0" />
          </feComponentTransfer>
        </filter>
      </defs>

      <g filter="url(#fl-tear)">
        <rect
          x={TEAR_INSET}
          y={TEAR_INSET}
          width={PAPER_VB_W - TEAR_INSET * 2}
          height={PAPER_VB_H - TEAR_INSET * 2}
          fill="url(#fl-paper)"
        />
        <rect
          x={TEAR_INSET}
          y={TEAR_INSET}
          width={PAPER_VB_W - TEAR_INSET * 2}
          height={PAPER_VB_H - TEAR_INSET * 2}
          fill="url(#fl-paper-light)"
        />
        <rect
          x={TEAR_INSET}
          y={TEAR_INSET}
          width={PAPER_VB_W - TEAR_INSET * 2}
          height={PAPER_VB_H - TEAR_INSET * 2}
          fill="url(#fl-paper-edges)"
        />
        <rect
          x={TEAR_INSET}
          y={TEAR_INSET}
          width={PAPER_VB_W - TEAR_INSET * 2}
          height={PAPER_VB_H - TEAR_INSET * 2}
          filter="url(#fl-mottle)"
          style={{ mixBlendMode: "multiply" }}
        />
        <rect
          x={TEAR_INSET}
          y={TEAR_INSET}
          width={PAPER_VB_W - TEAR_INSET * 2}
          height={PAPER_VB_H - TEAR_INSET * 2}
          filter="url(#fl-grain)"
          style={{ mixBlendMode: "multiply" }}
        />
      </g>
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
        <Image
          src={ENVELOPE_IMAGE}
          alt=""
          width={ENVELOPE_WIDTH}
          height={ENVELOPE_HEIGHT}
          priority
          className="block w-16 rotate-[-3deg] drop-shadow-[0_12px_22px_rgba(0,0,0,0.5)]"
        />
        {/* Attention glow until the letter has been opened once */}
        {pulse && (
          <span
            aria-hidden
            className="absolute inset-1 -z-10 animate-ping rounded-lg bg-amber-200/45"
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
              className="relative flex max-h-[min(92vh,860px)] w-full max-w-[620px] flex-col overflow-y-auto overscroll-contain outline-none"
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
                      {copied ? (
                        <Tick02Icon
                          className="h-3 w-3"
                          style={{ color: INK }}
                        />
                      ) : (
                        <Copy01Icon
                          className="h-3 w-3"
                          style={{ color: INK }}
                        />
                      )}
                    </button>
                    at checkout.
                  </p>
                  <button
                    type="button"
                    onClick={() => {
                      openPricingModal({ discountCode: DISCOUNT_CODE });
                      closeLetter();
                    }}
                    className="inline-flex h-7 cursor-pointer items-center gap-1 rounded-full bg-black px-3 text-[calc(var(--letter-small)*0.95)] font-semibold text-[#fdf8ea] outline-none transition-opacity hover:opacity-80 focus-visible:ring-2 focus-visible:ring-black/60 active:scale-95"
                  >
                    Get the discount
                    <ArrowRightIcon
                      className="h-3 w-3"
                      style={{ color: PAPER_CREAM }}
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
                  href={MEETING_URL}
                  target="_blank"
                  rel="noreferrer"
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
