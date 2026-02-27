import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig, spring, interpolate, Img, staticFile } from "remotion";
import { COLORS } from "../constants";

export const S04_LogoBloom: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Radial bloom
  const bloomProgress = spring({ frame, fps, config: { damping: 40 } });
  const bloomScale = interpolate(bloomProgress, [0, 1], [0.3, 1.5]);
  const bloomOpacity = interpolate(bloomProgress, [0, 0.3, 0.7, 1], [0, 0.4, 0.3, 0.2]);

  // Logo appears at frame 8 — text_w_logo_black already includes the icon, no duplicate needed
  const logoProgress = spring({ frame: frame - 8, fps, config: { damping: 15, stiffness: 100 } });
  const logoScale = interpolate(logoProgress, [0, 1], [0.6, 1.0]);
  const logoOpacity = interpolate(logoProgress, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });
  // Exit
  const exitProgress = spring({ frame: frame - 88, fps, config: { damping: 200 } });
  const exitScale = interpolate(exitProgress, [0, 1], [1, 1.05], { extrapolateLeft: "clamp" });
  const exitOpacity = interpolate(exitProgress, [0, 1], [1, 0], { extrapolateLeft: "clamp" });

  return (
    <AbsoluteFill
      style={{
        background: COLORS.bgLight,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      {/* Radial bloom */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          background: `radial-gradient(ellipse at center, ${COLORS.primary}22 0%, transparent 70%)`,
          transform: `scale(${bloomScale})`,
          opacity: bloomOpacity,
          pointerEvents: "none",
        }}
      />

      {/* Text+logo mark — single image, no duplicate icon */}
      <div
        style={{
          transform: `scale(${exitScale * logoScale})`,
          opacity: exitOpacity * logoOpacity,
        }}
      >
        <Img
          src={staticFile("images/logos/text_w_logo_black.webp")}
          style={{ height: 200, objectFit: "contain", display: "block" }}
        />
      </div>
    </AbsoluteFill>
  );
};
