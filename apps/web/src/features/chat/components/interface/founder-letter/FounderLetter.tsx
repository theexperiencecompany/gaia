"use client";

import { Modal, ModalContent } from "@heroui/modal";
import {
  CancelIcon,
  CheckmarkCircle02Icon,
  CircleArrowRight02Icon,
  Copy01Icon,
} from "@icons";
import { useReducedMotion } from "motion/react";
import * as m from "motion/react-m";
import Image from "next/image";
import { type CSSProperties, useCallback, useEffect, useState } from "react";

import { RaisedButton } from "@/components/ui/raised-button";
import { isOfferLive } from "@/config/offer";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import { toast } from "@/lib/toast";
import { usePricingModalStore } from "@/stores/pricingModalStore";
import { useUserStore } from "@/stores/userStore";

import {
  BODY_FONT,
  DISCOUNT_CODE,
  DISCOUNT_PERCENT,
  DISCOUNT_TERMS,
  DISCOUNT_YEARLY_NOTE,
  INK,
  INK_SOFT,
  LETTER_DISMISSED_KEY,
  LETTER_OPENED_KEY,
  LETTER_PARAGRAPHS,
  MEETING_CTA,
  MEETING_SENTENCE,
  MEETING_URL,
  OFFER_LEAD,
  SALUTATION_FALLBACK,
  SIGNATURE_NAME,
  SIGNATURE_ROLE,
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

/**
 * The letter tilts and settles onto the screen rather than fading in. HeroUI
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

/** The offer button reads as ink on paper: RaisedButton's flat black treatment. */
const CTA_BLACK = "#000000";

/** The sealed envelope the letter arrives in: the artwork file as it is. */
const ENVELOPE_IMAGE = "/images/icons/sealed-envelope.webp";
const ENVELOPE_WIDTH = 1536;
const ENVELOPE_HEIGHT = 1024;

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
          <stop offset="0%" stopColor="#fdf7dc" />
          <stop offset="35%" stopColor="#f9eec1" />
          <stop offset="72%" stopColor="#f2e0a2" />
          <stop offset="100%" stopColor="#e6cd85" />
        </linearGradient>
        <radialGradient
          id="fl-paper-light"
          cx="0.18"
          cy="0.04"
          r="0.75"
          gradientUnits="objectBoundingBox"
        >
          <stop offset="0%" stopColor="#ffffff" stopOpacity="0.7" />
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
  // Both read in an effect, not in render, so server and client markup match.
  const [dismissed, setDismissed] = useState(false);
  const [hasOpened, setHasOpened] = useState(false);
  // An expired code fails loudly at Dodo's checkout, so the letter stops
  // offering it rather than sending readers into a 500.
  const [offerLive, setOfferLive] = useState(false);
  const [copied, setCopied] = useState(false);
  const userName = useUserStore((s) => s.name);
  const openPricingModal = usePricingModalStore((s) => s.openModal);
  const reduceMotion = useReducedMotion();

  const firstName = userName.trim().split(" ")[0] || SALUTATION_FALLBACK;

  useEffect(() => {
    const isDismissed = !!window.localStorage.getItem(LETTER_DISMISSED_KEY);
    setDismissed(isDismissed);
    setHasOpened(!!window.localStorage.getItem(LETTER_OPENED_KEY));
    setOfferLive(isOfferLive());
    // The denominator for every other event in this funnel: without it, an
    // open rate has no base to divide by.
    if (!isDismissed) {
      trackEvent(ANALYTICS_EVENTS.FOUNDER_LETTER_SHOWN, {
        discount_code: DISCOUNT_CODE,
      });
    }
  }, []);

  const openLetter = useCallback(() => {
    const firstOpen = !window.localStorage.getItem(LETTER_OPENED_KEY);
    window.localStorage.setItem(LETTER_OPENED_KEY, "1");
    setHasOpened(true);
    setIsOpen(true);
    trackEvent(ANALYTICS_EVENTS.FOUNDER_LETTER_OPENED, {
      first_open: firstOpen,
      discount_code: DISCOUNT_CODE,
      discount_percent: DISCOUNT_PERCENT,
    });
  }, []);

  // Dismissing hides the envelope for good on this device.
  const dismissLetter = useCallback(() => {
    window.localStorage.setItem(LETTER_DISMISSED_KEY, "1");
    setDismissed(true);
    trackEvent(ANALYTICS_EVENTS.FOUNDER_LETTER_DISMISSED, {
      discount_code: DISCOUNT_CODE,
    });
  }, []);

  const closeLetter = useCallback(() => setIsOpen(false), []);

  // Voice mode hides the letter, but hiding it only stops it rendering — the
  // component stays mounted, so an open letter would leave the body scroll
  // locked with nothing on screen to explain why. Hiding it closes it.
  useEffect(() => {
    if (hidden) setIsOpen(false);
  }, [hidden]);

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
    trackEvent(ANALYTICS_EVENTS.FOUNDER_LETTER_CODE_COPIED, {
      discount_code: DISCOUNT_CODE,
    });
    toast.success(`Code ${DISCOUNT_CODE} copied, it's yours`);
    window.setTimeout(() => setCopied(false), 2000);
  }, []);

  if (hidden || dismissed) return null;

  return (
    <>
      {/* A folded letter, waiting in the bottom-right corner above the composer. */}
      <div className="fixed right-4 bottom-24 z-40 flex flex-col items-end gap-1">
        <m.button
          type="button"
          onClick={openLetter}
          aria-label="A letter from Aryan Randeriya"
          title="A letter from Aryan"
          className="isolate cursor-pointer rounded-md outline-none focus-visible:ring-2 focus-visible:ring-[#00bbff]"
          initial={false}
          whileHover={reduceMotion ? undefined : { scale: 1.06 }}
          whileTap={reduceMotion ? undefined : { scale: 0.94 }}
          // A jump, not a float: two hops, then it sits still long enough to
          // stop being noise.
          // It jumps for attention until it has been read, then settles.
          animate={
            reduceMotion || hasOpened ? undefined : { y: [0, -16, 0, -7, 0] }
          }
          transition={
            reduceMotion || hasOpened
              ? undefined
              : {
                  y: {
                    duration: 1.1,
                    times: [0, 0.28, 0.52, 0.72, 0.9],
                    ease: "easeOut",
                    repeat: Number.POSITIVE_INFINITY,
                    repeatDelay: 2.6,
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
            className="block w-20 rotate-[-3deg]"
          />
        </m.button>
        {hasOpened && (
          <button
            type="button"
            onClick={dismissLetter}
            className="cursor-pointer pr-1 text-[11px] font-normal text-zinc-400 outline-none transition-colors hover:text-zinc-200 focus-visible:ring-2 focus-visible:ring-[#00bbff]"
          >
            Don't show again
          </button>
        )}
      </div>

      {/* HeroUI owns the dialog semantics: focus trap, Escape, scroll lock and
          focus restoration to the envelope. The paper is its own surface, so
          the modal's own background and shadow are stripped off. */}
      <Modal
        isOpen={isOpen}
        onClose={closeLetter}
        hideCloseButton
        aria-label="A letter from Aryan Randeriya"
        classNames={{
          backdrop: "bg-black/70 backdrop-blur-sm",
          wrapper: "items-center justify-center p-3 sm:p-6",
          base: "m-0 max-h-[min(92vh,860px)] w-full max-w-[620px] overflow-y-auto overscroll-contain bg-transparent shadow-none",
        }}
        motionProps={LETTER_MOTION[reduceMotion ? "reduced" : "full"]}
      >
        <ModalContent>
          <div className="relative flex flex-col" style={LETTER_TYPOGRAPHY}>
            <PaperBackdrop />

            {/* Close */}
            <button
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
                {LETTER_PARAGRAPHS.map((paragraph) => (
                  <p key={paragraph}>{paragraph}</p>
                ))}
              </div>

              {/* The offer, seamless and inline, while the code still works */}
              {offerLive && (
                <div className="mt-3 space-y-2">
                  <p
                    style={{
                      fontSize: "var(--letter-body)",
                      lineHeight: "var(--letter-body-lh)",
                    }}
                  >
                    {OFFER_LEAD} Take{" "}
                    <strong className="font-bold">
                      {DISCOUNT_PERCENT}% off
                    </strong>{" "}
                    with{" "}
                    <button
                      type="button"
                      onClick={copyCode}
                      aria-label={`Copy the discount code ${DISCOUNT_CODE}`}
                      title={copied ? "Copied" : "Copy code"}
                      className="mx-0.5 inline-flex translate-y-[-1px] cursor-pointer items-center gap-1 rounded px-1 align-middle font-bold outline-none transition-colors hover:bg-black/10 focus-visible:ring-2 focus-visible:ring-black/60 active:scale-95"
                      style={{ color: INK }}
                    >
                      {DISCOUNT_CODE}
                      {copied ? (
                        <CheckmarkCircle02Icon className="h-3.5 w-3.5" />
                      ) : (
                        <Copy01Icon className="h-3 w-3" />
                      )}
                    </button>
                    at checkout. {DISCOUNT_YEARLY_NOTE}
                  </p>
                  <RaisedButton
                    color={CTA_BLACK}
                    size="sm"
                    className="mt-1 px-4 font-semibold"
                    onClick={() => {
                      trackEvent(
                        ANALYTICS_EVENTS.FOUNDER_LETTER_DISCOUNT_CTA_CLICKED,
                        {
                          discount_code: DISCOUNT_CODE,
                          discount_percent: DISCOUNT_PERCENT,
                        },
                      );
                      openPricingModal({
                        discountCode: DISCOUNT_CODE,
                        discountPercent: DISCOUNT_PERCENT,
                      });
                      closeLetter();
                    }}
                  >
                    Claim {DISCOUNT_PERCENT}% off
                    <CircleArrowRight02Icon className="h-4 w-4" />
                  </RaisedButton>
                  <p
                    className="opacity-60"
                    style={{ fontSize: "calc(var(--letter-small) * 0.92)" }}
                  >
                    {DISCOUNT_TERMS}
                  </p>
                </div>
              )}

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
                onClick={() =>
                  trackEvent(ANALYTICS_EVENTS.FOUNDER_LETTER_MEETING_CLICKED)
                }
                className="mt-1 inline-flex items-center gap-1.5 text-[calc(var(--letter-small)*1.05)] font-semibold underline decoration-[1.5px] underline-offset-4 outline-none transition-opacity hover:opacity-70 focus-visible:ring-2 focus-visible:ring-black/60"
              >
                {MEETING_CTA}
              </a>

              {/* Signature: draws itself in, stroke by stroke */}
              <div className="mt-6">
                <Signature active={isOpen} scale="clamp(1.05, 0.14vh, 1.35)" />
              </div>
              <div
                className="mt-1 flex flex-col leading-snug font-normal"
                style={{ fontSize: "var(--letter-small)" }}
              >
                <span className="font-medium">{SIGNATURE_NAME}</span>
                <span>{SIGNATURE_ROLE}</span>
              </div>
            </div>
          </div>
        </ModalContent>
      </Modal>
    </>
  );
}
