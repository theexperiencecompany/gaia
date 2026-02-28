import type React from "react";
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { COLORS, FONTS } from "../constants";

export const S03_BetterWay: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Beat 1: "10s of apps."
  const beat1Progress = spring({
    frame,
    fps,
    config: { damping: 15, stiffness: 100 },
  });
  const beat1Blur = interpolate(beat1Progress, [0, 1], [20, 0]);
  const beat1Scale = interpolate(beat1Progress, [0, 1], [0.95, 1.0]);
  const beat1Opacity = interpolate(beat1Progress, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });

  // Beat 2: "One assistant." — slides up with slight delay
  const beat2Progress = spring({
    frame: frame - 18,
    fps,
    config: { damping: 18, stiffness: 120 },
  });
  const beat2Y = interpolate(beat2Progress, [0, 1], [40, 0]);
  const beat2Opacity = interpolate(beat2Progress, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });

  // Subtle breathe hold
  const breathe = interpolate(
    Math.sin((frame / 60) * Math.PI * 2),
    [-1, 1],
    [1.0, 1.005],
  );

  // Exit: scale up slightly + fade (next transition overlaps 20f, exit starts at ~frame 80)
  const exitP = spring({ frame: frame - 80, fps, config: { damping: 200 } });
  const exitScale = interpolate(exitP, [0, 1], [1.0, 1.08], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const exitOpacity = interpolate(exitP, [0, 1], [1, 0], {
    extrapolateLeft: "clamp",
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
        gap: 16,
      }}
    >
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 24,
          transform: `scale(${breathe * exitScale})`,
          opacity: exitOpacity,
        }}
      >
        {/* Beat 1: "10s of apps." */}
        <div
          style={{
            fontFamily: FONTS.display,
            textTransform: "uppercase" as const,
            fontSize: 180,
            fontWeight: 700,
            color: COLORS.textDark,
            textAlign: "center",
            lineHeight: 1.0,
            filter: `blur(${beat1Blur}px)`,
            transform: `scale(${beat1Scale})`,
            opacity: beat1Opacity,
          }}
        >
          10s of apps.
        </div>

        {/* Beat 2: "One assistant." in cyan */}
        <div
          style={{
            fontFamily: FONTS.display,
            textTransform: "uppercase" as const,
            fontSize: 180,
            fontWeight: 700,
            color: COLORS.primary,
            textAlign: "center",
            lineHeight: 1.0,
            transform: `translateY(${beat2Y}px)`,
            opacity: beat2Opacity,
          }}
        >
          One assistant.
        </div>
      </div>
    </AbsoluteFill>
  );
};
