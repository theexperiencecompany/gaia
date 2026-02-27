import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig, spring, interpolate, Img, staticFile } from "remotion";
import { COLORS } from "../constants";

const TOOL_POSITIONS = [
  { x: -500, y: -200 },
  { x: 0, y: -300 },
  { x: 500, y: -200 },
  { x: -650, y: 0 },
  { x: 650, y: 0 },
  { x: -500, y: 250 },
  { x: -200, y: 320 },
  { x: 500, y: 250 },
  { x: -300, y: -250 },
  { x: 300, y: 250 },
  { x: 200, y: -320 },
  { x: -400, y: 150 },
  { x: 400, y: -100 },
];

const TOOL_ICONS = [
  "images/icons/macos/gmail.webp",
  "images/icons/macos/slack.webp",
  "images/icons/macos/notion.webp",
  "images/icons/macos/calendar.webp",
  "images/icons/macos/google_docs.webp",
  "images/icons/macos/figma.webp",
  "images/icons/macos/github.webp",
  "images/icons/macos/trello.webp",
  "images/icons/macos/whatsapp.webp",
  "images/icons/macos/asana.webp",
  "images/icons/macos/discord.webp",
  "images/icons/macos/telegram.webp",
  "images/icons/macos/zoom.webp",
];

interface ToolIconProps {
  index: number;
  position: { x: number; y: number };
  iconSrc: string;
}

const ToolIcon: React.FC<ToolIconProps> = ({ index, position, iconSrc }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const entryDelay = index * 3;
  const entryProgress = spring({
    frame: frame - entryDelay,
    fps,
    config: { damping: 8, stiffness: 120 },
  });

  const scale = interpolate(entryProgress, [0, 1], [0, 1]);
  const x = interpolate(entryProgress, [0, 1], [position.x * 2, position.x]);
  const y = interpolate(entryProgress, [0, 1], [position.y * 2, position.y]);

  // Shake after settling
  const settledFrame = Math.max(0, frame - entryDelay - 20);
  const shake = interpolate(settledFrame % 20, [0, 10, 20], [-3, 3, -3]);
  const shakeOpacity = entryProgress > 0.7 ? 1 : 0;

  // Collapse at the end (snap to center + fade)
  const collapseStart = 75;
  const collapseProgress = spring({
    frame: frame - collapseStart,
    fps,
    config: { damping: 200 },
  });

  const finalX = frame >= collapseStart ? interpolate(collapseProgress, [0, 1], [x, 0]) : x;
  const finalY = frame >= collapseStart ? interpolate(collapseProgress, [0, 1], [y, 0]) : y;
  const finalOpacity =
    frame >= collapseStart
      ? interpolate(collapseProgress, [0.5, 1], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })
      : 1;

  return (
    <div
      style={{
        position: "absolute",
        left: "50%",
        top: "50%",
        transform: `translate(${finalX - 36}px, ${finalY - 36}px) scale(${scale}) rotate(${shakeOpacity ? shake : 0}deg)`,
        opacity: finalOpacity,
      }}
    >
      <Img
        src={staticFile(iconSrc)}
        style={{
          width: 72,
          height: 72,
          borderRadius: 16,
          display: "block",
        }}
      />
    </div>
  );
};

export const S02_ToolChaos: React.FC = () => {
  return (
    <AbsoluteFill style={{ background: COLORS.bgLight }}>
      {TOOL_POSITIONS.map((pos, i) => (
        <ToolIcon
          key={i}
          index={i}
          position={pos}
          iconSrc={TOOL_ICONS[i] || "images/icons/macos/github.webp"}
        />
      ))}
    </AbsoluteFill>
  );
};
