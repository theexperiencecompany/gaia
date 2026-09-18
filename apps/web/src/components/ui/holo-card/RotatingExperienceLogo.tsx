"use client";

import Image from "next/image";
import { useId } from "react";

import { CARD_IMAGES } from "./constants";

interface RotatingExperienceLogoProps {
  size?: number;
  text?: string;
  durationSec?: number;
}

const DEFAULT_TEXT = "The Experience Company  •   ";

// Shared spin keyframes live in globals.css (`holoRotatingLogoSpin`); the
// <svg> below only sets its own duration, which stays inline under the
// holo-card no-inline-styles override (animation is an allowed property).
const SPIN_KEYFRAMES_NAME = "holoRotatingLogoSpin";

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
  const r = size * 0.46;
  const circumference = 2 * Math.PI * r;
  const fontSize = Math.max(8, Math.round(size * 0.12));

  const circlePath = `M ${cx} ${cy - r} a ${r} ${r} 0 1 1 0 ${2 * r} a ${r} ${r} 0 1 1 0 ${-2 * r}`;

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
      <svg
        viewBox={`0 0 ${size} ${size}`}
        width={size}
        height={size}
        className="absolute inset-0"
        style={{
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
          className="font-serif font-semibold text-white"
          fill="currentColor"
          fillOpacity="0.95"
          fontSize={fontSize}
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
        className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2"
      />
    </div>
  );
}
