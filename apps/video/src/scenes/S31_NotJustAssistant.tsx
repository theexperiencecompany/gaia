import React from "react";
import {
  AbsoluteFill,
  useCurrentFrame,
  useVideoConfig,
  spring,
  interpolate,
} from "remotion";
import { COLORS, FONTS } from "../constants";

const WORDS = ["isn't", "just", "an", "assistant."];

export const S31_NotJustAssistant: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // GAIA title slams up from below with a bouncy spring
  const gaiaSpring = spring({
    frame,
    fps,
    config: { damping: 8, stiffness: 200 },
  });
  const gaiaY = interpolate(gaiaSpring, [0, 1], [150, 0]);

  return (
    <AbsoluteFill
      style={{
        background: COLORS.bgLight,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 32,
        overflow: "hidden",
      }}
    >
      {/* GAIA title */}
      <div
        style={{
          fontFamily: FONTS.display,
          fontSize: 280,
          fontWeight: 800,
          color: COLORS.textDark,
          letterSpacing: "-0.03em",
          lineHeight: 1,
          transform: `translateY(${gaiaY}px)`,
        }}
      >
        GAIA
      </div>

      {/* Staggered word row */}
      <div
        style={{
          display: "flex",
          flexDirection: "row",
          alignItems: "baseline",
          gap: 24,
          overflow: "hidden",
        }}
      >
        {WORDS.map((word, i) => {
          const wordFrame = frame - (20 + i * 8);
          const wordSpring = spring({
            frame: wordFrame,
            fps,
            config: { damping: 8, stiffness: 200 },
          });
          const wordY = interpolate(wordSpring, [0, 1], [50, 0]);
          const wordOpacity = interpolate(
            wordSpring,
            [0, 0.15],
            [0, 1],
            { extrapolateRight: "clamp" }
          );

          return (
            <div
              key={word}
              style={{
                fontFamily: FONTS.body,
                fontSize: 96,
                fontWeight: 500,
                color: COLORS.zinc600,
                transform: `translateY(${wordY}px)`,
                opacity: wordOpacity,
              }}
            >
              {word}
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
