"use client";

import { Modal, ModalContent } from "@heroui/modal";
import { CancelIcon } from "@icons";
import type { CSSProperties } from "react";

import { useFounderLetter } from "@/features/chat/hooks/useFounderLetter";
import { useFirstSteps } from "@/features/first-steps";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import {
  BODY_FONT,
  INK,
  INK_SOFT,
  LETTER_PARAGRAPHS,
  MEETING_CTA,
  MEETING_SENTENCE,
  MEETING_URL,
  SIGNATURE_NAME,
  SIGNATURE_ROLE,
} from "./content";
import { LetterEnvelope } from "./LetterEnvelope";
import { LetterOffer } from "./LetterOffer";
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
  const {
    firstName,
    dismissed,
    hasOpened,
    offerLive,
    copied,
    isOpen,
    reduceMotion,
    openLetter,
    dismissLetter,
    closeLetter,
    copyCode,
    claimOffer,
  } = useFounderLetter(hidden);
  // The expanded activation checklist floats in this exact corner at the same
  // z-index, and overlapped the envelope. One owner at a time: the checklist
  // wins while it is open, the envelope returns once it is collapsed or done.
  const { isVisible: checklistOpen, collapsed: checklistCollapsed } =
    useFirstSteps();

  if (hidden || dismissed || (checklistOpen && !checklistCollapsed))
    return null;

  return (
    <>
      <LetterEnvelope
        hasOpened={hasOpened}
        reduceMotion={reduceMotion}
        onOpen={openLetter}
        onDismiss={dismissLetter}
      />

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

              {offerLive && (
                <LetterOffer
                  copied={copied}
                  onCopyCode={copyCode}
                  onClaim={claimOffer}
                />
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
