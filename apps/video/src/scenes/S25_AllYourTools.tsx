import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig, spring, interpolate } from "remotion";
import { COLORS, FONTS } from "../constants";
import { FloatingToolIcon } from "../components/FloatingToolIcon";

const TOOL_ICONS = [
  { src: "images/icons/notion.webp",         alt: "Notion",          x: -580, y: -180, rotation: -12, size: 72, floatPhase: 0 },
  { src: "images/icons/gmail.svg",            alt: "Gmail",           x: -420, y:  120, rotation:   8, size: 80, floatPhase: 1 },
  { src: "images/icons/googlecalendar.webp",  alt: "Google Calendar", x:  480, y: -200, rotation:  10, size: 72, floatPhase: 2 },
  { src: "images/icons/macos/slack.webp",      alt: "Slack",           x:  520, y:  140, rotation:  -6, size: 72, floatPhase: 3 },
  { src: "images/icons/googledocs.webp",      alt: "Google Docs",     x: -300, y: -280, rotation:   5, size: 68, floatPhase: 4 },
  { src: "images/icons/figma.svg",            alt: "Figma",           x:  320, y: -300, rotation: -10, size: 68, floatPhase: 5 },
  { src: "images/icons/github.svg",           alt: "GitHub",          x: -540, y:  240, rotation:   6, size: 72, floatPhase: 0.5 },
  { src: "images/icons/googlesheets.webp",    alt: "Sheets",          x:  420, y:  280, rotation:  -8, size: 64, floatPhase: 1.5 },
  { src: "images/icons/trello.svg",           alt: "Trello",          x: -200, y:  300, rotation:  12, size: 64, floatPhase: 2.5 },
  { src: "images/icons/macos/whatsapp.webp",  alt: "WhatsApp",        x:  580, y:    0, rotation:  -4, size: 64, floatPhase: 3.5 },
];

export const S25_AllYourTools: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Beat 1: "All your tools."
  const beat1Words = ["All", "your", "tools."];
  const beat1Delays = [0, 4, 8];

  // Beat 2: "One assistant." (cyan) — appears 20 frames later
  const beat2Words = ["One", "assistant."];
  const beat2Delays = [20, 24];

  return (
    <AbsoluteFill style={{ background: COLORS.bgLight }}>
      {/* Floating tool icons */}
      {TOOL_ICONS.map((tool, i) => (
        <FloatingToolIcon
          key={i}
          src={tool.src}
          alt={tool.alt}
          x={tool.x}
          y={tool.y}
          rotation={tool.rotation}
          size={tool.size}
          delay={10 + i * 6}
          floatPhase={tool.floatPhase}
        />
      ))}

      {/* Central text */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          gap: 8,
          pointerEvents: "none",
        }}
      >
        {/* Beat 1 words */}
        <div style={{ display: "flex", gap: 32, justifyContent: "center" }}>
          {beat1Words.map((word, i) => {
            const prog = spring({
              frame: frame - beat1Delays[i],
              fps,
              config: { damping: 18, stiffness: 120 },
            });
            return (
              <span
                key={i}
                style={{
                  display: "inline-block",
                  fontFamily: FONTS.display,
                  fontSize: 220,
                  fontWeight: 800,
                  color: COLORS.textDark,
                  lineHeight: 1.0,
                  transform: `translateY(${interpolate(prog, [0, 1], [40, 0])}px)`,
                  opacity: interpolate(prog, [0, 0.1], [0, 1], { extrapolateRight: "clamp" }),
                }}
              >
                {word}
              </span>
            );
          })}
        </div>

        {/* Beat 2 words — CYAN */}
        <div style={{ display: "flex", gap: 32, justifyContent: "center" }}>
          {beat2Words.map((word, i) => {
            const prog = spring({
              frame: frame - beat2Delays[i],
              fps,
              config: { damping: 18, stiffness: 120 },
            });
            return (
              <span
                key={i}
                style={{
                  display: "inline-block",
                  fontFamily: FONTS.display,
                  fontSize: 220,
                  fontWeight: 800,
                  color: COLORS.primary,
                  lineHeight: 1.0,
                  transform: `translateY(${interpolate(prog, [0, 1], [40, 0])}px)`,
                  opacity: interpolate(prog, [0, 0.1], [0, 1], { extrapolateRight: "clamp" }),
                }}
              >
                {word}
              </span>
            );
          })}
        </div>
      </div>
    </AbsoluteFill>
  );
};
