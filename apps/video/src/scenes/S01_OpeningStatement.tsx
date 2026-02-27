import React from "react";
import {
  AbsoluteFill,
  useCurrentFrame,
  interpolate,
} from "remotion";
import { COLORS, FONTS } from "../constants";

// One word per beat — instant hard cut, no fade, tiny scale punch on enter
const WORDS = [
  { text: "YOU",      startFrame: 0,  exitFrame: 8  },
  { text: "DO",       startFrame: 8,  exitFrame: 16 },
  { text: "THIS",     startFrame: 16, exitFrame: 28 },
  { text: "MANUALLY", startFrame: 28, exitFrame: 48 },
  { text: "EVERY",    startFrame: 48, exitFrame: 56 },
  { text: "DAY.",     startFrame: 56, exitFrame: 999 },
];

interface WordProps {
  text: string;
  startFrame: number;
  exitFrame: number;
}

const Word: React.FC<WordProps> = ({ text, startFrame, exitFrame }) => {
  const frame = useCurrentFrame();
  if (frame < startFrame || frame >= exitFrame) return null;

  // Instant appear — no opacity fade. Tiny scale punch (1.07 → 1.0) in 4 frames.
  const elapsed = frame - startFrame;
  const punchT = Math.min(1, elapsed / 4);
  const scale = interpolate(punchT, [0, 0.5, 1], [1.07, 1.01, 1.0]);

  return (
    <div
      style={{
        fontFamily: FONTS.display,
        fontSize: 200,
        fontWeight: 800,
        color: COLORS.textDark,
        lineHeight: 1.0,
        letterSpacing: "-0.02em",
        textTransform: "uppercase",
        textAlign: "center",
        transform: `translateX(-50%) scale(${scale})`,
        transformOrigin: "center center",
        position: "absolute",
        left: "50%",
        whiteSpace: "nowrap",
      }}
    >
      {text}
    </div>
  );
};

export const S01_OpeningStatement: React.FC = () => {
  return (
    <AbsoluteFill style={{ background: COLORS.bgLight, overflow: "hidden" }}>
      {/* Words — centered, one at a time, instant hard cut */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <div
          style={{
            position: "relative",
            width: "100%",
            height: 240,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          {WORDS.map((word, i) => (
            <Word key={i} text={word.text} startFrame={word.startFrame} exitFrame={word.exitFrame} />
          ))}
        </div>
      </div>
    </AbsoluteFill>
  );
};
