import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig, spring, interpolate } from "remotion";
import { COLORS, FONTS } from "../constants";

export const S32_ProductivityOS: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Cyan bloom behind text
  const bloomProgress = spring({ frame, fps, config: { damping: 40 } });
  const bloomScale = interpolate(bloomProgress, [0, 1], [0, 2.0]);

  // Line 1: "It's your" — fades in small + muted
  const line1Progress = spring({ frame, fps, config: { damping: 200 } });
  const line1Opacity = interpolate(line1Progress, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });

  // Line 2: "Productivity" — character by character, appears at frame 10
  const chars = "Productivity".split("");
  const charAnimations = chars.map((_, i) => {
    const prog = spring({
      frame: frame - 10 - i * 3,
      fps,
      config: { damping: 15 },
    });
    return {
      scale: interpolate(prog, [0, 1], [0.7, 1.0]),
      opacity: interpolate(prog, [0, 0.1], [0, 1], { extrapolateRight: "clamp" }),
      y: interpolate(prog, [0, 1], [20, 0]),
    };
  });

  // Line 3: "Operating System." — slides up as one unit at ~frame 50
  const line3Progress = spring({ frame: frame - 50, fps, config: { damping: 18, stiffness: 120 } });
  const line3Scale = interpolate(line3Progress, [0, 1], [0.9, 1.0]);
  const line3Opacity = interpolate(line3Progress, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });

  // Scan line sweeps at frame 80
  const scanX = interpolate(frame - 80, [0, 40], [-960, 960], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const showScan = frame >= 80;

  return (
    <AbsoluteFill
      style={{
        background: COLORS.bgLight,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 4,
        overflow: "hidden",
      }}
    >
      {/* Cyan radial bloom */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          background: `radial-gradient(ellipse at center, ${COLORS.primary}08 0%, transparent 65%)`,
          transform: `scale(${bloomScale})`,
          pointerEvents: "none",
        }}
      />

      {/* Scan line */}
      {showScan && (
        <div
          style={{
            position: "absolute",
            top: "50%",
            left: 0,
            width: "100%",
            height: 2,
            background: COLORS.primary,
            opacity: 0.4,
            transform: `translateX(${scanX}px)`,
            pointerEvents: "none",
            zIndex: 10,
          }}
        />
      )}

      {/* Line 1 */}
      <div
        style={{
          fontFamily: FONTS.body,
          fontSize: 72,
          fontWeight: 500,
          color: COLORS.zinc600,
          textAlign: "center",
          opacity: line1Opacity,
        }}
      >
        It&apos;s your
      </div>

      {/* Line 2: "Productivity" — hero word */}
      <div style={{ display: "flex" }}>
        {chars.map((char, i) => (
          <span
            key={i}
            style={{
              display: "inline-block",
              fontFamily: FONTS.display,
              fontSize: 200,
              color: COLORS.textDark,
              lineHeight: 1.0,
              letterSpacing: "-0.02em",
              transform: `translateY(${charAnimations[i].y}px) scale(${charAnimations[i].scale})`,
              opacity: charAnimations[i].opacity,
            }}
          >
            {char}
          </span>
        ))}
      </div>

      {/* Line 3: "Operating System." in cyan */}
      <div
        style={{
          fontFamily: FONTS.display,
          fontSize: 180,
          color: COLORS.primary,
          lineHeight: 1.0,
          letterSpacing: "-0.02em",
          transform: `scale(${line3Scale})`,
          opacity: line3Opacity,
        }}
      >
        Operating System.
      </div>
    </AbsoluteFill>
  );
};
