import type React from "react";
import {
  AbsoluteFill,
  Audio,
  Sequence,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { COLORS, FONTS } from "../constants";
import { SFX } from "../sfx";

export const S32_ProductivityOS: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const bloomOpacity = interpolate(frame, [0, 20], [0, 1], {
    extrapolateRight: "clamp",
  });

  // Lead-in: "So you can focus on" — snaps in immediately
  const line1P = spring({ frame, fps, config: { damping: 200 } });
  const line1Y = interpolate(line1P, [0, 1], [28, 0]);
  const line1Opacity = interpolate(line1P, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill
      style={{
        background: COLORS.bgLight,
        overflow: "hidden",
      }}
    >
      {/* Audio cues */}
      <Sequence from={26}><Audio src={SFX.whoosh} volume={0.35} /></Sequence>

      {/* Cyan radial bloom */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          background: `radial-gradient(ellipse at 20% 55%, ${COLORS.primary}14 0%, transparent 60%)`,
          opacity: bloomOpacity,
          pointerEvents: "none",
        }}
      />

      {/* Text block — left-aligned, vertically centered */}
      <div
        style={{
          position: "absolute",
          left: 120,
          top: "50%",
          transform: "translateY(-50%)",
          display: "flex",
          flexDirection: "column",
          alignItems: "flex-start",
          gap: 0,
        }}
      >
        {/* Lead-in */}
        <div
          style={{
            fontFamily: FONTS.body,
            fontSize: 44,
            fontWeight: 300,
            color: COLORS.zinc400,
            letterSpacing: "0.01em",
            transform: `translateY(${line1Y}px)`,
            opacity: line1Opacity,
            marginBottom: 8,
          }}
        >
          So you can focus on
        </div>

        {/* WHAT MATTERS — hero */}
        <div
          style={{
            display: "flex",
            fontFamily: FONTS.display,
            fontSize: 190,
            fontWeight: 800,
            lineHeight: 0.9,
            letterSpacing: "-0.04em",
            marginBottom: 24,
          }}
        >
          {"WHAT MATTERS".split("").map((char, i) => {
            const charP = spring({
              frame: frame - (5 + i * 1.5),
              fps,
              config: { damping: 18, stiffness: 140 },
            });
            const charY = interpolate(charP, [0, 1], [70, 0]);
            const charOpacity = interpolate(charP, [0, 0.08], [0, 1], {
              extrapolateRight: "clamp",
            });
            return (
              <span
                key={`wm-${i}`}
                style={{
                  display: "inline-block",
                  color: COLORS.textDark,
                  transform: `translateY(${charY}px)`,
                  opacity: charOpacity,
                  whiteSpace: "pre",
                }}
              >
                {char === " " ? "\u00A0" : char}
              </span>
            );
          })}
        </div>

        {/* EVERYTHING ELSE, HANDLED. — cyan punctuation */}
        <div
          style={{
            display: "flex",
            fontFamily: FONTS.display,
            fontSize: 80,
            fontWeight: 700,
            lineHeight: 1.0,
            letterSpacing: "-0.02em",
          }}
        >
          {"EVERYTHING ELSE, HANDLED.".split("").map((char, i) => {
            const charP = spring({
              frame: frame - (26 + i * 1.5),
              fps,
              config: { damping: 18, stiffness: 140 },
            });
            const charY = interpolate(charP, [0, 1], [50, 0]);
            const charOpacity = interpolate(charP, [0, 0.08], [0, 1], {
              extrapolateRight: "clamp",
            });
            return (
              <span
                key={`eh-${i}`}
                style={{
                  display: "inline-block",
                  color: COLORS.primary,
                  transform: `translateY(${charY}px)`,
                  opacity: charOpacity,
                  whiteSpace: "pre",
                }}
              >
                {char === " " ? "\u00A0" : char}
              </span>
            );
          })}
        </div>
      </div>
    </AbsoluteFill>
  );
};
