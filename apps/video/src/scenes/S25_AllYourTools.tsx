import type React from "react";
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { FloatingToolIcon } from "../components/FloatingToolIcon";
import { COLORS, FONTS } from "../constants";

const TOOL_ICONS = [
  // Far left column
  {
    src: "images/icons/macos/notion.webp",
    alt: "Notion",
    x: -780,
    y: -280,
    rotation: -12,
    size: 96,
    floatPhase: 0,
  },
  {
    src: "images/icons/macos/github.webp",
    alt: "GitHub",
    x: -800,
    y: 20,
    rotation: 6,
    size: 92,
    floatPhase: 0.5,
  },
  {
    src: "images/icons/macos/whatsapp.webp",
    alt: "WhatsApp",
    x: -760,
    y: 300,
    rotation: -8,
    size: 88,
    floatPhase: 1,
  },

  // Mid-left column
  {
    src: "images/icons/macos/gmail.webp",
    alt: "Gmail",
    x: -580,
    y: -340,
    rotation: 8,
    size: 96,
    floatPhase: 1.5,
  },
  {
    src: "images/icons/macos/slack.webp",
    alt: "Slack",
    x: -600,
    y: 260,
    rotation: 10,
    size: 92,
    floatPhase: 2,
  },

  // Top row
  {
    src: "images/icons/macos/google_docs.webp",
    alt: "Google Docs",
    x: -220,
    y: -360,
    rotation: 5,
    size: 90,
    floatPhase: 2.5,
  },
  {
    src: "images/icons/macos/figma.webp",
    alt: "Figma",
    x: 180,
    y: -370,
    rotation: -10,
    size: 90,
    floatPhase: 3,
  },
  {
    src: "images/icons/macos/discord.webp",
    alt: "Discord",
    x: 540,
    y: -330,
    rotation: 7,
    size: 88,
    floatPhase: 3.5,
  },

  // Bottom row
  {
    src: "images/icons/macos/calendar.webp",
    alt: "Google Calendar",
    x: -240,
    y: 360,
    rotation: 12,
    size: 90,
    floatPhase: 4,
  },
  {
    src: "images/icons/macos/telegram.webp",
    alt: "Telegram",
    x: 160,
    y: 370,
    rotation: -6,
    size: 90,
    floatPhase: 4.5,
  },
  {
    src: "images/icons/macos/todoist.webp",
    alt: "Todoist",
    x: 560,
    y: 310,
    rotation: 9,
    size: 88,
    floatPhase: 5,
  },

  // Far right column
  {
    src: "images/icons/macos/sheets.webp",
    alt: "Sheets",
    x: 780,
    y: -260,
    rotation: -8,
    size: 96,
    floatPhase: 5.5,
  },
  {
    src: "images/icons/macos/linear.webp",
    alt: "Linear",
    x: 820,
    y: 40,
    rotation: 4,
    size: 92,
    floatPhase: 0.7,
  },
  {
    src: "images/icons/macos/zoom.webp",
    alt: "Zoom",
    x: 770,
    y: 310,
    rotation: -11,
    size: 88,
    floatPhase: 1.2,
  },

  // Mid-right
  {
    src: "images/icons/macos/trello.webp",
    alt: "Trello",
    x: 620,
    y: -100,
    rotation: -5,
    size: 92,
    floatPhase: 1.8,
  },
  {
    src: "images/icons/macos/asana.webp",
    alt: "Asana",
    x: -640,
    y: -80,
    rotation: 13,
    size: 92,
    floatPhase: 2.3,
  },
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
                  textTransform: "uppercase" as const,
                  fontSize: 220,
                  fontWeight: 700,
                  color: COLORS.textDark,
                  lineHeight: 1.0,
                  transform: `translateY(${interpolate(prog, [0, 1], [40, 0])}px)`,
                  opacity: interpolate(prog, [0, 0.1], [0, 1], {
                    extrapolateRight: "clamp",
                  }),
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
                  textTransform: "uppercase" as const,
                  fontSize: 220,
                  fontWeight: 700,
                  color: COLORS.primary,
                  lineHeight: 1.0,
                  transform: `translateY(${interpolate(prog, [0, 1], [40, 0])}px)`,
                  opacity: interpolate(prog, [0, 0.1], [0, 1], {
                    extrapolateRight: "clamp",
                  }),
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
