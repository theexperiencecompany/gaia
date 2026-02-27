import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig, spring, interpolate } from "remotion";
import { COLORS, FONTS } from "../constants";

export const S29_OneDashboard: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Line 1: "One dashboard."
  const words1 = ["One", "dashboard."];
  const line1Chars = words1.map((_, i) => {
    const prog = spring({ frame: frame - i * 5, fps, config: { damping: 18, stiffness: 120 } });
    return {
      y: interpolate(prog, [0, 1], [40, 0]),
      opacity: interpolate(prog, [0, 0.1], [0, 1], { extrapolateRight: "clamp" }),
    };
  });

  // Line 2: "Everything." (cyan) — 15 frames later
  const line2Progress = spring({ frame: frame - 15, fps, config: { damping: 18, stiffness: 120 } });
  const line2Scale = interpolate(line2Progress, [0, 1], [0.9, 1.0]);
  const line2Opacity = interpolate(line2Progress, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });
  const line2Y = interpolate(line2Progress, [0, 1], [40, 0]);

  // Sub-text at frame 50
  const subProgress = spring({ frame: frame - 50, fps, config: { damping: 200 } });
  const subOpacity = interpolate(subProgress, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });

  // Breathing
  const breathe = interpolate(Math.sin((frame / 80) * Math.PI * 2), [-1, 1], [1.0, 1.008]);

  return (
    <AbsoluteFill style={{ background: COLORS.bgLight }}>
      {/* Typography */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          gap: 8,
          transform: `scale(${breathe})`,
        }}
      >
        {/* Line 1 */}
        <div style={{ display: "flex", gap: 32 }}>
          {words1.map((word, i) => (
            <span
              key={i}
              style={{
                display: "inline-block",
                fontFamily: FONTS.display,
                fontSize: 200,
                fontWeight: 800,
                color: COLORS.textDark,
                lineHeight: 1.0,
                letterSpacing: "0",
                transform: `translateY(${line1Chars[i].y}px)`,
                opacity: line1Chars[i].opacity,
              }}
            >
              {word}
            </span>
          ))}
        </div>

        {/* Line 2: "Everything." in cyan */}
        <div
          style={{
            fontFamily: FONTS.display,
            fontSize: 200,
            fontWeight: 800,
            color: COLORS.primary,
            lineHeight: 1.0,
            letterSpacing: "0",
            transform: `translateY(${line2Y}px) scale(${line2Scale})`,
            opacity: line2Opacity,
          }}
        >
          Everything.
        </div>

        {/* Sub-text */}
        <div
          style={{
            fontFamily: FONTS.body,
            fontSize: 32,
            fontWeight: 500,
            color: COLORS.zinc600,
            textAlign: "center",
            marginTop: 48,
            opacity: subOpacity,
          }}
        >
          Gmail. Calendar. Todos. Goals. All in one.
        </div>
      </div>
    </AbsoluteFill>
  );
};
