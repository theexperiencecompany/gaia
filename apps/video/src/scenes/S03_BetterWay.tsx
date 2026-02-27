import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig, spring, interpolate } from "remotion";
import { COLORS, FONTS } from "../constants";

export const S03_BetterWay: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Beat 1: main text
  const beat1Progress = spring({ frame, fps, config: { damping: 15, stiffness: 100 } });
  const beat1Blur = interpolate(beat1Progress, [0, 1], [20, 0]);
  const beat1Scale = interpolate(beat1Progress, [0, 1], [0.95, 1.0]);
  const beat1Opacity = interpolate(beat1Progress, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });

  // Accent line
  const lineProgress = spring({ frame: frame - 10, fps, config: { damping: 30 } });
  const lineWidth = interpolate(lineProgress, [0, 1], [0, 400]);

  // Beat 2: sub-text
  const beat2Progress = spring({ frame: frame - 20, fps, config: { damping: 200 } });
  const beat2Y = interpolate(beat2Progress, [0, 1], [20, 0]);
  const beat2Opacity = interpolate(beat2Progress, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });

  // Subtle breathe hold
  const breathe = interpolate(
    Math.sin((frame / 60) * Math.PI * 2),
    [-1, 1],
    [1.0, 1.005],
  );

  // Cyan pulse on accent line
  const linePulse = interpolate(
    Math.sin((frame / 20) * Math.PI * 2),
    [-1, 1],
    [0.7, 1.0],
  );

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
          transform: `scale(${breathe})`,
        }}
      >
        {/* Beat 1 */}
        <div
          style={{
            fontFamily: FONTS.display,
            fontSize: 180,
            color: COLORS.textDark,
            textAlign: "center",
            lineHeight: 1.05,
            filter: `blur(${beat1Blur}px)`,
            transform: `scale(${beat1Scale})`,
            opacity: beat1Opacity,
          }}
        >
          There&apos;s a better way.
        </div>

        {/* Cyan accent line */}
        <div
          style={{
            width: lineWidth,
            height: 2,
            background: COLORS.primary,
            borderRadius: 1,
            opacity: linePulse,
          }}
        />

        {/* Beat 2 */}
        <div
          style={{
            fontFamily: FONTS.body,
            fontSize: 36,
            fontWeight: 400,
            color: COLORS.zinc600,
            textAlign: "center",
            transform: `translateY(${beat2Y}px)`,
            opacity: beat2Opacity,
          }}
        >
          Automate the repetitive. Reclaim your day.
        </div>
      </div>
    </AbsoluteFill>
  );
};
