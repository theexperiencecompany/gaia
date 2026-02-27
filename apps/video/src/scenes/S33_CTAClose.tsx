import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig, spring, interpolate, Img, staticFile } from "remotion";
import { COLORS, FONTS } from "../constants";

export const S33_CTAClose: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Logo springs in
  const logoProgress = spring({ frame, fps, config: { damping: 15 } });
  const logoScale = interpolate(logoProgress, [0, 0.5, 1], [0, 1.05, 1.0]);
  const logoOpacity = interpolate(logoProgress, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });

  // Subtle bloom rotation
  const bloomAngle = interpolate(frame, [0, 102], [0, 5]);

  // Wordmark at frame 8 — letter-spacing spring from 0.5em → 0.3em
  const wordProgress = spring({ frame: frame - 8, fps, config: { damping: 200 } });
  const wordOpacity = interpolate(wordProgress, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });
  const wordSpacing = interpolate(wordProgress, [0, 1], [0.5, 0.3]);

  // CTA button at frame 20
  const btnProgress = spring({ frame: frame - 20, fps, config: { damping: 22, stiffness: 100 } });
  const btnScale = interpolate(btnProgress, [0, 1], [0.8, 1.0]);
  const btnOpacity = interpolate(btnProgress, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });

  // Pulsing glow on button
  const glowPulse = Math.sin((frame / 20) * Math.PI) * 0.5 + 0.5;
  const glowSize = 20 + glowPulse * 20;
  const glowHex = Math.floor(glowPulse * 50 + 30).toString(16).padStart(2, "0");

  // Arrow nudge
  const arrowX = Math.sin((frame / 20) * Math.PI) * 4;

  // URL at frame 30
  const urlProgress = spring({ frame: frame - 30, fps, config: { damping: 200 } });
  const urlOpacity = interpolate(urlProgress, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });

  // Logo breathe
  const breatheScale = 1 + Math.sin((frame / 60) * Math.PI * 2) * 0.005;

  // Fade to black at the end
  const fadeOut = interpolate(frame, [82, 102], [0, 1], {
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
        gap: 0,
      }}
    >
      {/* Subtle bloom */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          background: `radial-gradient(ellipse at center, ${COLORS.primary}08 0%, transparent 60%)`,
          transform: `rotate(${bloomAngle}deg) scale(1.2)`,
          pointerEvents: "none",
        }}
      />

      <div
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 40,
          transform: `scale(${breatheScale})`,
        }}
      >
        {/* Logo */}
        <div
          style={{
            transform: `scale(${logoScale})`,
            opacity: logoOpacity,
          }}
        >
          <Img
            src={staticFile("images/logos/logo.webp")}
            style={{ width: 80, height: 80, objectFit: "contain", display: "block" }}
          />
        </div>

        {/* Wordmark */}
        <div
          style={{
            fontFamily: FONTS.body,
            fontSize: 80,
            fontWeight: 700,
            color: COLORS.textDark,
            letterSpacing: `${wordSpacing}em`,
            opacity: wordOpacity,
          }}
        >
          GAIA
        </div>

        {/* CTA Button */}
        <div
          style={{
            padding: "18px 48px",
            borderRadius: 14,
            background: COLORS.primary,
            color: "#000000",
            fontSize: 24,
            fontFamily: FONTS.body,
            fontWeight: 700,
            boxShadow: `0 0 ${glowSize}px #00bbff${glowHex}`,
            transform: `scale(${btnScale})`,
            opacity: btnOpacity,
            display: "flex",
            alignItems: "center",
            gap: 8,
          }}
        >
          Try GAIA Free
          <span style={{ display: "inline-block", transform: `translateX(${arrowX}px)` }}>
            →
          </span>
        </div>

        {/* URL */}
        <div
          style={{
            fontFamily: FONTS.body,
            fontSize: 28,
            fontWeight: 400,
            color: COLORS.zinc600,
            opacity: urlOpacity,
          }}
        >
          heygaia.io
        </div>
      </div>

      {/* Fade to black overlay */}
      {frame >= 82 && (
        <div
          style={{
            position: "absolute",
            inset: 0,
            background: "#000",
            opacity: fadeOut,
            pointerEvents: "none",
          }}
        />
      )}
    </AbsoluteFill>
  );
};
