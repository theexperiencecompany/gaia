import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig, spring, interpolate } from "remotion";
import { COLORS, FONTS } from "../constants";

export const S05_MeetGaia: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const chars1 = "Meet GAIA".split("");
  const chars2 = ".";

  // Line 1: character-by-character
  const line1Chars = chars1.map((_, i) => {
    const prog = spring({
      frame: frame - i * 3,
      fps,
      config: { damping: 25, stiffness: 150 },
    });
    return {
      y: interpolate(prog, [0, 1], [30, 0]),
      opacity: interpolate(prog, [0, 0.1], [0, 1], { extrapolateRight: "clamp" }),
    };
  });

  // Cyan dot animation
  const dotDelay = chars1.length * 3;
  const dotProg = spring({
    frame: frame - dotDelay,
    fps,
    config: { damping: 25, stiffness: 150 },
  });
  const dotY = interpolate(dotProg, [0, 1], [30, 0]);
  const dotOpacity = interpolate(dotProg, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });
  // Dot pulse after landing
  const dotPulseDelay = dotDelay + 15;
  const dotPulseProg = spring({
    frame: frame - dotPulseDelay,
    fps,
    config: { damping: 12 },
    durationInFrames: 20,
  });
  const dotScale = frame > dotPulseDelay ? interpolate(dotPulseProg, [0, 0.5, 1], [1, 1.3, 1.0]) : 1;

  // Line 2: blur reveal after 25 frames
  const line2Prog = spring({ frame: frame - 25, fps, config: { damping: 200 } });
  const line2Blur = interpolate(line2Prog, [0, 1], [20, 0]);
  const line2Scale = interpolate(line2Prog, [0, 1], [0.95, 1.0]);
  const line2Opacity = interpolate(line2Prog, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });

  // Subtle breathe hold
  const breathe = interpolate(
    Math.sin((frame / 80) * Math.PI * 2),
    [-1, 1],
    [1.0, 1.005],
  );

  // Dive zoom exit
  const exitProg = spring({ frame: frame - 90, fps, config: { damping: 200 } });
  const exitScale = interpolate(exitProg, [0, 1], [1.0, 1.15], { extrapolateLeft: "clamp" });
  const exitOpacity = interpolate(exitProg, [0, 1], [1, 0], { extrapolateLeft: "clamp" });

  return (
    <AbsoluteFill
      style={{
        background: COLORS.bgLight,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 28,
      }}
    >
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 28,
          transform: `scale(${breathe * exitScale})`,
          opacity: exitOpacity,
        }}
      >
        {/* Line 1: "Meet GAIA." with cyan period */}
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            justifyContent: "center",
            fontFamily: FONTS.display,
            fontSize: 220,
            lineHeight: 1.0,
            letterSpacing: "-0.02em",
          }}
        >
          {chars1.map((char, i) => (
            <span
              key={i}
              style={{
                display: "inline-block",
                color: COLORS.textDark,
                transform: `translateY(${line1Chars[i].y}px)`,
                opacity: line1Chars[i].opacity,
                whiteSpace: char === " " ? "pre" : "normal",
              }}
            >
              {char === " " ? "\u00a0" : char}
            </span>
          ))}
          <span
            style={{
              display: "inline-block",
              color: COLORS.primary,
              transform: `translateY(${dotY}px) scale(${dotScale})`,
              opacity: dotOpacity,
            }}
          >
            {chars2}
          </span>
        </div>

        {/* Line 2: subtitle */}
        <div
          style={{
            fontFamily: FONTS.body,
            fontSize: 42,
            fontWeight: 500,
            color: COLORS.zinc600,
            textAlign: "center",
            letterSpacing: "0.05em",
            filter: `blur(${line2Blur}px)`,
            transform: `scale(${line2Scale})`,
            opacity: line2Opacity,
          }}
        >
          Your Productivity Operating System.
        </div>
      </div>
    </AbsoluteFill>
  );
};
