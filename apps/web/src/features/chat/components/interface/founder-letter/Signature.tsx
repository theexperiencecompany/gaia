"use client";

import { useReducedMotion } from "motion/react";
import { type CSSProperties, useEffect, useRef, useState } from "react";

import { INK } from "./content";

/**
 * Aryan's handwritten signature — ported from his personal site
 * (aryanranderiya.com, github.com/aryanranderiya/website). Each letter is an
 * individual SVG whose path draws in via stroke-dashoffset, staggered
 * left-to-right, exactly like the homepage signature.
 *
 * Unlike the site (which draws on scroll), this draws when the letter opens —
 * `active` flips true on mount and the paths animate in.
 */

interface LetterDef {
  char: string;
  viewBox: string;
  width: number;
  height: number;
  path: string;
  dasharray: number;
  margin: string;
}

const LETTERS: LetterDef[] = [
  // A (uppercase)
  {
    char: "A",
    viewBox: "0 0 46 51",
    width: 46,
    height: 51,
    path: "M14.9987 32.0003C20.8769 23.2406 40.7942 1.02295 44.6176 1.58265C48.4411 2.14235 25.4397 26.0685 19.6688 50.0398C28.2839 11.7157 5.83642 32.6888 1.46688 33.1804C4.63512 27.4831 32.8719 20.946 44.7496 24.6628",
    dasharray: 190,
    margin: "0 -10px 0 -7px",
  },
  // r (lowercase)
  {
    char: "r",
    viewBox: "0 0 13 51",
    width: 13,
    height: 51,
    path: "M4.04688 23.3381L1.02539 30.1005C7.1047 22.5828 11.8527 19.8132 11.2412 24.1654",
    dasharray: 24,
    margin: "0 -3px 0 -1px",
  },
  // y (lowercase)
  {
    char: "y",
    viewBox: "0 0 21 51",
    width: 21,
    height: 51,
    path: "M12.7596 23.2466C11.7764 22.8447 9.49733 28.5405 10.2142 28.4672C10.931 28.3939 16.2577 23.541 16.1552 24.1849C16.7988 27.8118 2.76345 49.8665 1.16523 44.1016C0.00381581 39.4883 5.35733 40.4355 20.0861 24.6317",
    dasharray: 70,
    margin: "0 -4px 0 -9px",
  },
  // a (lowercase)
  {
    char: "a",
    viewBox: "0 0 13 51",
    width: 13,
    height: 51,
    path: "M5.99958 25C5.73591 21.1582 1.99899 25.5 1.49941 28C1.00013 30.5 7.65454 23.3545 7.65454 23.3545C3.5802 27.3691 3.29278 30.5313 4.09638 30.7478C5.08629 31.0263 12.2012 24.7466 12.2012 24.7466",
    dasharray: 36,
    margin: "0 -4px 0 0",
  },
  // n (lowercase)
  {
    char: "n",
    viewBox: "0 0 15 51",
    width: 15,
    height: 51,
    path: "M4.42188 23.1724L1.16211 28.4658C3.87099 25.9122 7.65167 23.2024 8.42922 23.7108C8.87781 23.9799 6.69468 26.9705 7.8311 27.4191C8.96753 27.8677 11.8983 25.565 14.0814 24.7575",
    dasharray: 27,
    margin: "0 -5px 0 0",
  },
];

const SPACE: "space" = "space";

const LETTERS_LAST_NAME: LetterDef[] = [
  // R (uppercase)
  {
    char: "R",
    viewBox: "0 0 58 51",
    width: 58,
    height: 51,
    path: "M12.0195 45.3685C19.1859 32.3806 23.0999 25.7226 32.0203 11.3685C21.5205 20.8685 5.01953 34.2139 1.01953 30.7139C6.01953 17.2138 71.5195 -7.28639 53.5188 13.7136C43.6613 25.2136 12.0195 41.7136 14.0195 38.2136C37.0871 17.3054 32.9838 44.188 46.7608 39.6997",
    dasharray: 235,
    margin: "0 -8px 0 -4px",
  },
  // a (lowercase)
  {
    char: "a",
    viewBox: "0 0 13 51",
    width: 13,
    height: 51,
    path: "M5.99958 25C5.73591 21.1582 1.99899 25.5 1.49941 28C1.00013 30.5 7.65454 23.3545 7.65454 23.3545C3.5802 27.3691 3.29278 30.5313 4.09638 30.7478C5.08629 31.0263 12.2012 24.7466 12.2012 24.7466",
    dasharray: 36,
    margin: "0 -4px 0 0",
  },
  // n (lowercase)
  {
    char: "n",
    viewBox: "0 0 15 51",
    width: 15,
    height: 51,
    path: "M4.42188 23.1724L1.16211 28.4658C3.87099 25.9122 7.65167 23.2024 8.42922 23.7108C8.87781 23.9799 6.69468 26.9705 7.8311 27.4191C8.96753 27.8677 11.8983 25.565 14.0814 24.7575",
    dasharray: 27,
    margin: "0 -5px 0 0",
  },
  // d (lowercase)
  {
    char: "d",
    viewBox: "0 0 20 51",
    width: 20,
    height: 51,
    path: "M6.08732 26.1229C8.23611 18.5681 -0.331592 27.5316 1.908 28.6301C7.01852 28.6767 10.2741 20.6086 19.1923 6.23315C9.56633 22.4841 2.35848 34.2032 2.35848 34.2032",
    dasharray: 73,
    margin: "0 -11.3px 0 0",
  },
  // e (lowercase)
  {
    char: "e",
    viewBox: "0 0 11 51",
    width: 11,
    height: 51,
    path: "M3.07713 25.3392C3.03314 27.7282 6.78706 24.9554 6.03999 23.505C4.44172 21.2653 -0.294204 28.3892 2.71291 28.2186C5.35941 27.9626 10.2422 24.7207 10.2422 24.7207",
    dasharray: 22,
    margin: "0 -4px 0 0",
  },
  // r (lowercase)
  {
    char: "r",
    viewBox: "0 0 13 51",
    width: 13,
    height: 51,
    path: "M4.04688 23.3381L1.02539 30.1005C7.1047 22.5828 11.8527 19.8132 11.2412 24.1654",
    dasharray: 24,
    margin: "0 -3px 0 -1px",
  },
  // i (lowercase)
  {
    char: "i",
    viewBox: "0 0 9 51",
    width: 9,
    height: 51,
    path: "M3.7548 22.9229C2.60207 23.529 -0.752212 29.5295 1.61166 28.7618C3.97553 27.994 5.61205 25.8726 7.67374 24.721",
    dasharray: 16,
    margin: "0 -3.5px 0 0",
  },
  // y (lowercase)
  {
    char: "y",
    viewBox: "0 0 21 51",
    width: 21,
    height: 51,
    path: "M12.7596 23.2466C11.7764 22.8447 9.49733 28.5405 10.2142 28.4672C10.931 28.3939 16.2577 23.541 16.1552 24.1849C16.7988 27.8118 2.76345 49.8665 1.16523 44.1016C0.00381581 39.4883 5.35733 40.4355 20.0861 24.6317",
    dasharray: 70,
    margin: "0 -4px 0 -9px",
  },
  // a (lowercase)
  {
    char: "a",
    viewBox: "0 0 13 51",
    width: 13,
    height: 51,
    path: "M5.99958 25C5.73591 21.1582 1.99899 25.5 1.49941 28C1.00013 30.5 7.65454 23.3545 7.65454 23.3545C3.5802 27.3691 3.29278 30.5313 4.09638 30.7478C5.08629 31.0263 12.2012 24.7466 12.2012 24.7466",
    dasharray: 36,
    margin: "0 -4px 0 0",
  },
];

/**
 * The signature is one frozen sequence of glyphs, so a glyph's position in it
 * *is* its identity — "the second a in Randeriya" is a different mark from the
 * first. The key is therefore computed once here, as data, rather than from a
 * render-time index.
 */
const ALL_ITEMS: { key: string; item: LetterDef | "space" }[] = [
  ...LETTERS,
  SPACE,
  ...LETTERS_LAST_NAME,
].map((item, position) => ({
  key: item === "space" ? `space-${position}` : `${item.char}-${position}`,
  item,
}));

interface SignatureProps {
  /** The letters draw in once this flips true. */
  active: boolean;
  /** Render scale. The signature is authored at 51px cap-height; a CSS
   * length (e.g. clamp()) is fine so the letter can fit any viewport. */
  scale?: number | string;
  className?: string;
}

/**
 * Draw timing: the letter's entrance takes ~0.55s, so the pen starts after
 * it settles (0.65s) and each letter takes 0.6s with a 0.09s stagger. The
 * whole signature takes ~2.5s of visible handwriting.
 */
const DRAW_START_S = 0.65;
const DRAW_PER_LETTER_S = 0.6;
const DRAW_STAGGER_S = 0.09;

export function Signature({ active, scale = 1.6, className }: SignatureProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const reduceMotion = useReducedMotion();
  // Paths start hidden (offset = dasharray) and flip to 0 inside a
  // requestAnimationFrame, guaranteeing the hidden state was committed and
  // painted first: CSS transitions need a previous computed value to animate
  // from, and a state flip in the same commit as mount would skip the draw.
  const [draw, setDraw] = useState(false);

  useEffect(() => {
    if (!active) return;
    const frame = requestAnimationFrame(() => setDraw(true));
    return () => cancelAnimationFrame(frame);
  }, [active]);

  let letterIndex = 0;

  return (
    <div
      ref={containerRef}
      role="img"
      aria-label="Aryan Randeriya's handwritten signature"
      className={className}
    >
      <div
        className="flex h-[51px] origin-[0_50%] scale-[var(--sig-scale)] items-center justify-start"
        style={{ "--sig-scale": scale } as CSSProperties}
      >
        {ALL_ITEMS.map(({ key, item }) => {
          if (item === "space") {
            return <div key={key} className="h-[51px] w-3" />;
          }

          const currentIndex = letterIndex;
          letterIndex++;

          return (
            <div key={key} style={{ margin: item.margin }}>
              <svg
                viewBox={item.viewBox}
                height={item.height}
                width={item.width}
                className="overflow-visible"
              >
                <title>{item.char}</title>
                <path
                  d={item.path}
                  fill="none"
                  stroke={INK}
                  strokeWidth={1.8}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  style={{
                    strokeDasharray: item.dasharray,
                    // Hidden until the letter opens, then the pen draws it in.
                    // Reduced motion: appear instantly, no draw.
                    strokeDashoffset: draw ? 0 : item.dasharray,
                    transition: reduceMotion
                      ? "none"
                      : `stroke-dashoffset ${DRAW_PER_LETTER_S}s cubic-bezier(0.19, 1, 0.22, 1) ${
                          DRAW_START_S + currentIndex * DRAW_STAGGER_S
                        }s`,
                  }}
                />
              </svg>
            </div>
          );
        })}
      </div>
    </div>
  );
}
