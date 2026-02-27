import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig, spring, interpolate, Img, staticFile } from "remotion";
import { COLORS, FONTS } from "../constants";
import { TypingText } from "../components/TypingText";
import { Search01Icon } from "@theexperiencecompany/gaia-icons/solid-rounded";

export const S34_SearchBarCTA: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Search bar entrance
  const barProgress = spring({ frame, fps, config: { damping: 200 } });
  const barOpacity = interpolate(barProgress, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });
  const barY = interpolate(barProgress, [0, 1], [30, 0]);

  // Go button scale-up entrance at frame 70
  const btnProgress = spring({ frame: frame - 70, fps, config: { damping: 22, stiffness: 100 } });
  const btnScale = interpolate(btnProgress, [0, 1], [0.7, 1.0]);
  const btnOpacity = interpolate(btnProgress, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });

  // Bottom line fade at frame 80
  const bottomProgress = spring({ frame: frame - 80, fps, config: { damping: 200 } });
  const bottomOpacity = interpolate(bottomProgress, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });

  return (
    <AbsoluteFill
      style={{
        background: COLORS.bgLight,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 48,
      }}
    >
      {/* TOP HALF: Search bar */}
      <div
        style={{
          transform: `translateY(${barY}px)`,
          opacity: barOpacity,
          display: "flex",
          alignItems: "center",
          width: 800,
          height: 80,
          borderRadius: 40,
          background: "#f4f4f5",
          border: "2px solid #e4e4e7",
          padding: "0 16px 0 24px",
          gap: 12,
        }}
      >
        {/* Search icon */}
        <Search01Icon size={28} color={COLORS.zinc400} style={{ flexShrink: 0 }} />

        {/* Typing text */}
        <div style={{ flex: 1, display: "flex", alignItems: "center" }}>
          <TypingText
            text="heygaia.io"
            framesPerChar={3}
            delay={20}
            cursorColor={COLORS.zinc400}
            style={{
              fontFamily: FONTS.body,
              fontSize: 28,
              color: COLORS.textDark,
              fontWeight: 400,
            }}
          />
        </div>

        {/* Go button */}
        <div
          style={{
            background: COLORS.primary,
            color: "#000",
            borderRadius: 28,
            padding: "12px 28px",
            fontFamily: FONTS.body,
            fontWeight: 600,
            fontSize: 22,
            transform: `scale(${btnScale})`,
            opacity: btnOpacity,
            flexShrink: 0,
            display: "flex",
            alignItems: "center",
            gap: 6,
          }}
        >
          Go →
        </div>
      </div>

      {/* BOTTOM HALF: GAIA branding line */}
      <div
        style={{
          opacity: bottomOpacity,
          display: "flex",
          alignItems: "center",
          gap: 16,
        }}
      >
        <Img
          src={staticFile("images/logos/logo.webp")}
          style={{ width: 48, height: 48, objectFit: "contain" }}
        />
        <span
          style={{
            fontFamily: FONTS.display,
            fontWeight: 800,
            fontSize: 52,
            color: COLORS.textDark,
          }}
        >
          GAIA
        </span>
        <span
          style={{
            fontFamily: FONTS.body,
            fontSize: 36,
            color: COLORS.zinc600,
            fontWeight: 400,
          }}
        >
          — now in beta
        </span>
      </div>
    </AbsoluteFill>
  );
};
