"use client";

import Image from "next/image";
import { useId } from "react";

import { CARD_IMAGES } from "./constants";

interface RotatingExperienceLogoProps {
  size?: number;
  /** Text repeated around the circle. Will be duplicated automatically so
   *  two copies sit 180° apart. */
  text?: string;
  /** Seconds per full revolution. Higher = slower. */
  durationSec?: number;
}

const DEFAULT_TEXT = "The Experience Company  •   ";

const SPIN_KEYFRAMES_NAME = "holoRotatingLogoSpin";

/**
 * Circular badge: Experience logo at the centre, the company name running
 * twice around the perimeter on a single full-circle path with bullet
 * separators between copies. `textLength` is set to the path's circumference
 * so glyphs always fit exactly — no overflow, no cut-off, regardless of
 * badge size or font metrics. The whole SVG spins via a CSS keyframe; the
 * inner logo stays static and centred.
 */
export function RotatingExperienceLogo({
  size = 88,
  text = DEFAULT_TEXT,
  durationSec = 22,
}: RotatingExperienceLogoProps) {
  const reactId = useId();
  const pathId = `holoRingPath${reactId}`.replace(/:/g, "");

  const cx = size / 2;
  const cy = size / 2;
  const imgSize = Math.round(size * 0.56);
  // Text baseline radius. Pulled slightly in from the badge edge so the
  // ascenders have breathing room and don't touch the perforations.
  const r = size * 0.46;
  const circumference = 2 * Math.PI * r;
  // Generous natural font size; lengthAdjust scales glyphs down if the
  // doubled string would overflow, so we never get visual cropping.
  const fontSize = Math.max(8, Math.round(size * 0.12));

  // Full circle, traversed CW (sweep=1 in y-down coords) starting at 12
  // o'clock. CW gives east-pointing tangents at the top of the circle so
  // glyphs there read upright; the bottom half is naturally upside-down,
  // which is fine because the badge is rotating and that half sweeps up to
  // upright once per revolution.
  const circlePath = `M ${cx} ${cy - r} a ${r} ${r} 0 1 1 0 ${2 * r} a ${r} ${r} 0 1 1 0 ${-2 * r}`;

  // Doubled so the bullet/text pattern shows on both sides.
  const ringText = `${text}${text}`;

  return (
    <div
      aria-hidden
      style={{
        position: "relative",
        width: size,
        height: size,
        pointerEvents: "none",
      }}
    >
      <style>{`
        @keyframes ${SPIN_KEYFRAMES_NAME} {
          from { transform: rotate(0deg); }
          to   { transform: rotate(360deg); }
        }
      `}</style>
      <svg
        viewBox={`0 0 ${size} ${size}`}
        width={size}
        height={size}
        style={{
          position: "absolute",
          inset: 0,
          animation: `${SPIN_KEYFRAMES_NAME} ${durationSec}s linear infinite`,
          transformOrigin: "center center",
          overflow: "visible",
        }}
      >
        <title>The Experience Company</title>
        <defs>
          <path id={pathId} d={circlePath} fill="none" />
        </defs>
        <text
          fill="rgba(255,255,255,0.95)"
          fontSize={fontSize}
          style={{
            fontFamily: "var(--font-aeonik), system-ui, sans-serif",
            fontWeight: 600,
          }}
        >
          <textPath
            href={`#${pathId}`}
            startOffset="0"
            textLength={circumference}
            lengthAdjust="spacingAndGlyphs"
          >
            {ringText}
          </textPath>
        </text>
      </svg>
      <Image
        src={CARD_IMAGES.EXPERIENCE_LOGO}
        alt=""
        width={imgSize}
        height={imgSize}
        priority
        unoptimized
        style={{
          position: "absolute",
          top: "50%",
          left: "50%",
          transform: "translate(-50%, -50%)",
        }}
      />
    </div>
  );
}
