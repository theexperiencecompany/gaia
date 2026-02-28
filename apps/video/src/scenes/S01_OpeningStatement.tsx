import React from "react";
import {
  AbsoluteFill,
  useCurrentFrame,
  interpolate,
} from "remotion";
import { COLORS, FONTS } from "../constants";

// One word per beat — instant hard cut, no fade, tiny scale punch on enter
const WORDS = [
  { text: "STOP",   startFrame: 0,   exitFrame: 10,  color: "#ff4444" },
  { text: "DOING",  startFrame: 10,  exitFrame: 20,  color: COLORS.textDark },
  { text: "GRUNT",  startFrame: 20,  exitFrame: 32,  color: COLORS.zinc400 },
  { text: "WORK.",  startFrame: 32,  exitFrame: 999, color: COLORS.primary },
];

interface WordProps {
  text: string;
  startFrame: number;
  exitFrame: number;
  color: string;
}

const Word: React.FC<WordProps> = ({ text, startFrame, exitFrame, color }) => {
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
        color,
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
  const frame = useCurrentFrame();

  // White flash at word cut frames
  const FLASH_FRAMES = [10, 20, 32];
  const flashOpacity = FLASH_FRAMES.reduce((acc, f) => {
    const dist = Math.abs(frame - f);
    return Math.max(acc, dist <= 1 ? interpolate(dist, [0, 1], [0.6, 0]) : 0);
  }, 0);

  return (
    <AbsoluteFill style={{ background: COLORS.bgLight, overflow: "hidden" }}>
      {/* White flash at word cuts */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          background: "white",
          opacity: flashOpacity,
          pointerEvents: "none",
          zIndex: 10,
        }}
      />
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
            <Word key={i} text={word.text} startFrame={word.startFrame} exitFrame={word.exitFrame} color={word.color} />
          ))}
        </div>
      </div>
    </AbsoluteFill>
  );
};
