import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig, spring, interpolate } from "remotion";
import { COLORS, FONTS } from "../constants";

export const S32_ProductivityOS: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Background cyan bloom: scales from 0 to 2.5 with slow spring
  const bloomProgress = spring({ frame, fps, config: { damping: 40 } });
  const bloomScale = interpolate(bloomProgress, [0, 1], [0, 2.5]);

  // Line 1: "It's your" — slides in from left at frame 0
  const line1X = spring({ frame, fps, config: { damping: 22, stiffness: 150 } });
  const line1TranslateX = interpolate(line1X, [0, 1], [-300, 0]);

  // Line 2: "Productivity" — slams up from below at frame 10
  const line2Y = spring({
    frame: frame - 10,
    fps,
    config: { damping: 9, stiffness: 200 },
  });
  const line2TranslateY = interpolate(line2Y, [0, 1], [180, 0]);
  const line2Scale = interpolate(
    frame - 10,
    [0, 0.4 * fps * (1 / 30), fps * (1 / 30)],
    [1.25, 0.96, 1.0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );
  const line2Opacity = frame >= 10 ? 1 : 0;

  // Line 3: "Operating System." — slams in from right at frame 35
  const line3X = spring({
    frame: frame - 35,
    fps,
    config: { damping: 10, stiffness: 180 },
  });
  const line3TranslateX = interpolate(line3X, [0, 1], [400, 0]);
  const line3Opacity = frame >= 35 ? 1 : 0;

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
          transform: `scale(${bloomScale})`,
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
          transform: `translateX(${line1TranslateX}px)`,
        }}
      >
        It&apos;s your
      </div>

      {/* Line 2: "Productivity" */}
      <div
        style={{
          fontFamily: FONTS.display,
          fontSize: 220,
          fontWeight: 800,
          color: COLORS.textDark,
          lineHeight: 0.95,
          letterSpacing: "-0.03em",
          transform: `translateY(${line2TranslateY}px) scale(${line2Scale})`,
          opacity: line2Opacity,
        }}
      >
        Productivity
      </div>

      {/* Line 3: "Operating System." */}
      <div
        style={{
          fontFamily: FONTS.display,
          fontSize: 180,
          fontWeight: 800,
          color: COLORS.primary,
          lineHeight: 1.0,
          letterSpacing: "-0.02em",
          transform: `translateX(${line3TranslateX}px)`,
          opacity: line3Opacity,
        }}
      >
        Operating System.
      </div>
    </AbsoluteFill>
  );
};
