import type React from "react";
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { COLORS, FONTS } from "../constants";

export const S32_ProductivityOS: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Background cyan bloom: simple fade in, no scaling artifact
  const bloomOpacity = interpolate(frame, [0, 20], [0, 1], {
    extrapolateRight: "clamp",
  });

  // Line 1: "It's your" — fast snap up from below
  const line1P = spring({ frame, fps, config: { damping: 200 } });
  const line1Y = interpolate(line1P, [0, 1], [32, 0]);
  const line1Opacity = interpolate(line1P, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });

  // Line 2: "Productivity" — hero entrance, slight controlled spring (ONE element gets drama)
  const line2P = spring({
    frame: frame - 5,
    fps,
    config: { damping: 18, stiffness: 140 },
  });
  const line2Y = interpolate(line2P, [0, 1], [80, 0]);
  const line2Scale = interpolate(line2P, [0, 0.5, 1], [1.04, 0.98, 1.0]);
  const line2Opacity = interpolate(line2P, [0, 0.08], [0, 1], {
    extrapolateRight: "clamp",
  });

  // Line 3: "Operating System." — clean snap up, slightly after line 2 settles
  const line3P = spring({ frame: frame - 16, fps, config: { damping: 200 } });
  const line3Y = interpolate(line3P, [0, 1], [40, 0]);
  const line3Opacity = interpolate(line3P, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill
      style={{
        background: COLORS.bgLight,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 0,
        overflow: "hidden",
      }}
    >
      {/* Cyan radial bloom */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          background: `radial-gradient(ellipse at 50% 60%, ${COLORS.primary}18 0%, transparent 55%)`,
          opacity: bloomOpacity,
          pointerEvents: "none",
        }}
      />

      {/* Line 1: "It's your" */}
      <div
        style={{
          fontFamily: FONTS.body,
          fontSize: 80,
          fontWeight: 400,
          color: COLORS.zinc600,
          textAlign: "center",
          lineHeight: 1.1,
          transform: `translateY(${line1Y}px)`,
          opacity: line1Opacity,
          marginBottom: 20,
        }}
      >
        It&apos;s your
      </div>

      {/* Line 2: "Productivity" */}
      <div
        style={{
          fontFamily: FONTS.display,
          textTransform: "uppercase" as const,
          fontSize: 150,
          fontWeight: 700,
          color: COLORS.textDark,
          lineHeight: 0.95,
          letterSpacing: "-0.03em",
          transform: `translateY(${line2Y}px) scale(${line2Scale})`,
          opacity: line2Opacity,
        }}
      >
        Productivity
      </div>

      {/* Line 3: "Operating System." */}
      <div
        style={{
          fontFamily: FONTS.display,
          textTransform: "uppercase" as const,
          fontSize: 150,
          fontWeight: 700,
          color: COLORS.primary,
          lineHeight: 1.0,
          letterSpacing: "-0.02em",
          transform: `translateY(${line3Y}px)`,
          opacity: line3Opacity,
        }}
      >
        Operating System.
      </div>
    </AbsoluteFill>
  );
};
