import React from "react";
import {
  AbsoluteFill,
  Audio,
  Sequence,
  useCurrentFrame,
  useVideoConfig,
  spring,
  interpolate,
} from "remotion";
import { COLORS, FONTS } from "../constants";
import { SFX } from "../sfx";

export const S10_NextMorning: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Line 1: "Next morning." — fast, soft fade + slide up
  const line1Progress = spring({ frame, fps, config: { damping: 60, stiffness: 200 } });
  const line1Opacity = interpolate(line1Progress, [0, 0.3], [0, 1], { extrapolateRight: "clamp" });
  const line1Y = interpolate(line1Progress, [0, 1], [24, 0]);

  // Line 2: "8:00 AM" — slams up from below, 8 frame delay
  const line2Progress = spring({ frame: frame - 8, fps, config: { damping: 200 } });
  const line2Opacity = interpolate(line2Progress, [0, 0.15], [0, 1], { extrapolateRight: "clamp" });
  const line2Y = interpolate(line2Progress, [0, 1], [80, 0]);

  // Background glow fades in with line 1
  const glowOpacity = interpolate(line1Progress, [0, 1], [0, 1], { extrapolateRight: "clamp" });

  return (
    <AbsoluteFill>
      <Sequence from={0}>
        <Audio src={SFX.uiSwitch} volume={0.3} />
      </Sequence>
      <Sequence from={8}>
        <Audio src={SFX.whoosh} volume={0.3} />
      </Sequence>

      {/* Background */}
      <AbsoluteFill style={{ backgroundColor: COLORS.bgLight }} />

      {/* Radial glow */}
      <AbsoluteFill
        style={{
          background: `radial-gradient(ellipse at 50% 60%, ${COLORS.primary}15 0%, transparent 50%)`,
          opacity: glowOpacity,
        }}
      />

      {/* Centered content */}
      <AbsoluteFill
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          gap: 16,
        }}
      >
        {/* Line 1: "Next morning." */}
        <div
          style={{
            fontFamily: FONTS.body,
            fontSize: 48,
            fontWeight: 400,
            color: COLORS.zinc600,
            opacity: line1Opacity,
            transform: `translateY(${line1Y}px)`,
          }}
        >
          Next morning.
        </div>

        {/* Line 2: "8:00 AM" */}
        <div
          style={{
            fontFamily: FONTS.display,
            fontSize: 180,
            fontWeight: 700,
            color: COLORS.textDark,
            textTransform: "uppercase" as const,
            lineHeight: 1,
            opacity: line2Opacity,
            transform: `translateY(${line2Y}px)`,
          }}
        >
          8:00 AM
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
