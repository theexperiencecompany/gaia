import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig, spring, interpolate } from "remotion";
import { COLORS, FONTS } from "../constants";

export const S31_NotJustAssistant: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Horizontal line appears 10 frames before text
  const lineProgress = spring({ frame: frame - 0, fps, config: { damping: 200 } });
  const lineWidth = interpolate(lineProgress, [0, 1], [0, 600]);

  // Text: instant, decisive
  const textProgress = spring({ frame: frame - 10, fps, config: { damping: 200 } });
  const textOpacity = interpolate(textProgress, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });

  // Exit: slides up + fades
  const exitProgress = spring({ frame: frame - 52, fps, config: { damping: 200 } });
  const exitY = interpolate(exitProgress, [0, 1], [0, -20], { extrapolateLeft: "clamp" });
  const exitOpacity = interpolate(exitProgress, [0, 1], [1, 0], { extrapolateLeft: "clamp" });

  return (
    <AbsoluteFill
      style={{
        background: COLORS.bgLight,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 32,
      }}
    >
      {/* Stage-setting line */}
      <div
        style={{
          width: lineWidth,
          height: 1,
          background: "#d4d4d8",
          borderRadius: 1,
        }}
      />

      {/* Statement */}
      <div
        style={{
          fontFamily: FONTS.body,
          fontSize: 80,
          fontWeight: 500,
          color: COLORS.zinc600,
          textAlign: "center",
          opacity: textOpacity * exitOpacity,
          transform: `translateY(${exitY}px)`,
          letterSpacing: "-0.01em",
        }}
      >
        GAIA isn&apos;t just an assistant.
      </div>
    </AbsoluteFill>
  );
};
