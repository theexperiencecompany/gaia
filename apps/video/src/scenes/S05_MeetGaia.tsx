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
import { COLORS, FONTS } from "../constants";

export const S05_MeetGaia: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const chars = "Meet".split("");

  // Character-by-character for "Meet"
  const charAnims = chars.map((_, i) => {
    const prog = spring({
      frame: frame - i * 1.5,
      fps,
      config: { damping: 20, stiffness: 200 },
    });
    return {
      y: interpolate(prog, [0, 1], [30, 0]),
      opacity: interpolate(prog, [0, 0.1], [0, 1], {
        extrapolateRight: "clamp",
      }),
    };
  });

  // GAIA logo blooms in after "Meet" settles
  const logoDelay = chars.length * 1.5 + 4;
  const logoProg = spring({
    frame: frame - logoDelay,
    fps,
    config: { damping: 15, stiffness: 100 },
  });
  const logoScale = interpolate(logoProg, [0, 1], [0.75, 1.0]);
  const logoOpacity = interpolate(logoProg, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });

  // Radial bloom behind logo
  const bloomProgress = spring({
    frame: frame - logoDelay,
    fps,
    config: { damping: 40 },
  });
  const bloomScale = interpolate(bloomProgress, [0, 1], [0.3, 1.5]);
  const bloomOpacity = interpolate(
    bloomProgress,
    [0, 0.3, 0.7, 1],
    [0, 0.35, 0.25, 0.15],
  );

  // Line 2: blur reveal
  const line2Prog = spring({
    frame: frame - 30,
    fps,
    config: { damping: 200 },
  });
  const line2Blur = interpolate(line2Prog, [0, 1], [20, 0]);
  const line2Scale = interpolate(line2Prog, [0, 1], [0.95, 1.0]);
  const line2Opacity = interpolate(line2Prog, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });

  // Subtle breathe hold
  const breathe = interpolate(
    Math.sin((frame / 80) * Math.PI * 2),
    [-1, 1],
    [1.0, 1.005],
  );

  // Dive zoom exit
  const exitProg = spring({ frame: frame - 70, fps, config: { damping: 200 } });
  const exitScale = interpolate(exitProg, [0, 1], [1.0, 1.15], {
    extrapolateLeft: "clamp",
  });
  const exitOpacity = interpolate(exitProg, [0, 1], [1, 0], {
    extrapolateLeft: "clamp",
  });

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
      {/* Radial bloom behind logo */}
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

      <div
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 32,
          transform: `scale(${breathe * exitScale})`,
          opacity: exitOpacity,
        }}
      >
        {/* Row: "Meet" chars + GAIA logo on same line */}
        <div
          style={{
            display: "flex",
            flexDirection: "row",
            alignItems: "center",
            gap: 50,
          }}
        >
          {/* "Meet" character-by-character */}
          <div
            style={{
              display: "flex",
              fontSize: 180,
              lineHeight: 1.0,
              letterSpacing: "-0.02em",
              fontFamily: FONTS.display,
              textTransform: "uppercase" as const,
              fontWeight: 700,
            }}
          >
            {chars.map((char, i) => (
              <span
                key={i}
                style={{
                  display: "inline-block",
                  color: COLORS.textDark,
                  transform: `translateY(${charAnims[i].y}px)`,
                  opacity: charAnims[i].opacity,
                }}
              >
                {char}
              </span>
            ))}
          </div>

          {/* GAIA logo */}
          <div
            style={{
              transform: `scale(${logoScale})`,
              opacity: logoOpacity,
              display: "flex",
              alignItems: "center",
            }}
          >
            <Img
              src={staticFile("images/logos/text_w_logo_white.webp")}
              style={{ height: 230, objectFit: "contain", display: "block" }}
            />
          </div>
        </div>

        {/* Subtitle */}
        <div
          style={{
            fontFamily: FONTS.body,
            fontSize: 42,
            color: COLORS.white,
            textAlign: "center",
            letterSpacing: "0.05em",
            filter: `blur(${line2Blur}px)`,
            transform: `scale(${line2Scale})`,
            opacity: line2Opacity,
          }}
        >
          Your Proactive Personal Assistant
        </div>
      </div>
    </AbsoluteFill>
  );
};
