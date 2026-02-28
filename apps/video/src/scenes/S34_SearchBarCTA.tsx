import { Search01Icon } from "@theexperiencecompany/gaia-icons/solid-rounded";
import type React from "react";
import {
  AbsoluteFill,
  Img,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { TypingText } from "../components/TypingText";
import { COLORS, FONTS } from "../constants";

export const S34_SearchBarCTA: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Search bar entrance
  const barProgress = spring({ frame, fps, config: { damping: 200 } });
  const barOpacity = interpolate(barProgress, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });
  const barY = interpolate(barProgress, [0, 1], [30, 0]);

  // Go button scale-up entrance at frame 70
  const btnProgress = spring({
    frame: frame - 70,
    fps,
    config: { damping: 22, stiffness: 100 },
  });
  const btnScale = interpolate(btnProgress, [0, 1], [0.7, 1.0]);
  const btnOpacity = interpolate(btnProgress, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });

  // Bottom line fade at frame 80
  const bottomProgress = spring({
    frame: frame - 80,
    fps,
    config: { damping: 200 },
  });
  const bottomOpacity = interpolate(bottomProgress, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });

  // Headline: slides down from top, very fast snap
  const headlineP = spring({ frame, fps, config: { damping: 200 } });
  const headlineY = interpolate(headlineP, [0, 1], [-24, 0]);
  const headlineOpacity = interpolate(headlineP, [0, 0.08], [0, 1], {
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
        gap: 48,
      }}
    >
      {/* Subtle cyan glow behind search bar */}
      <div
        style={{
          position: "absolute",
          width: 1100,
          height: 300,
          borderRadius: "50%",
          background: `radial-gradient(ellipse at center, ${COLORS.primary}18 0%, transparent 70%)`,
          opacity: barOpacity,
          pointerEvents: "none",
        }}
      />

      {/* Headline */}
      <div
        style={{
          transform: `translateY(${headlineY}px)`,
          opacity: headlineOpacity,
          textAlign: "center",
        }}
      >
        <div
          style={{
            fontFamily: FONTS.display,
            fontSize: 72,
            fontWeight: 700,
            color: COLORS.textDark,
            textTransform: "uppercase" as const,
            letterSpacing: "-0.02em",
            lineHeight: 1.0,
          }}
        >
          Start for free.
        </div>
      </div>

      {/* TOP HALF: Search bar */}
      <div
        style={{
          transform: `translateY(${barY}px)`,
          opacity: barOpacity,
          display: "flex",
          alignItems: "center",
          width: 1000,
          height: 100,
          borderRadius: 50,
          background: COLORS.zinc900,
          border: "2px solid rgba(255,255,255,0.1)",
          padding: "0 20px 0 28px",
          gap: 16,
        }}
      >
        <Img
          src={staticFile("images/icons/google.webp")}
          style={{
            width: 80,
            height: 80,
            objectFit: "cover",
          }}
        />

        {/* Typing text */}
        <div style={{ flex: 1, display: "flex", alignItems: "center" }}>
          <TypingText
            text="heygaia.io"
            framesPerChar={3}
            delay={20}
            cursorColor={COLORS.zinc400}
            style={{
              fontFamily: FONTS.body,
              fontSize: 36,
              color: COLORS.textDark,
              fontWeight: 400,
            }}
          />
        </div>

        {/* Search button */}
        <div
          style={{
            background: COLORS.primary,
            borderRadius: 36,
            width: 64,
            height: 64,
            transform: `scale(${btnScale})`,
            opacity: btnOpacity,
            flexShrink: 0,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <Search01Icon size={30} style={{ color: "#000" }} />
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
          src={staticFile("images/logos/text_w_logo_white.webp")}
          style={{
            height: 64,
            objectFit: "contain",
          }}
        />
        <span
          style={{
            fontFamily: FONTS.body,
            fontSize: 44,
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
