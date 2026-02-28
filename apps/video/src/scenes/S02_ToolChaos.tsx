import type React from "react";
import {
  AbsoluteFill,
  Audio,
  Img,
  interpolate,
  Sequence,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { COLORS, FONTS } from "../constants";
import { SFX } from "../sfx";

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

  const finalX =
    frame >= collapseStart ? interpolate(collapseProgress, [0, 1], [x, 0]) : x;
  const finalY =
    frame >= collapseStart ? interpolate(collapseProgress, [0, 1], [y, 0]) : y;
  const finalOpacity =
    frame >= collapseStart
      ? interpolate(collapseProgress, [0.5, 1], [1, 0], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        })
      : 1;

  return (
    <div
      style={{
        position: "absolute",
        left: "50%",
        top: "50%",
        transform: `translate(${finalX - 48}px, ${finalY - 48}px) scale(${scale}) rotate(${shakeOpacity ? shake : 0}deg)`,
        opacity: finalOpacity,
      }}
    >
      <Img
        src={staticFile(iconSrc)}
        style={{
          width: 96,
          height: 96,
          borderRadius: 20,
          display: "block",
        }}
      />
    </div>
  );
};

export const S02_ToolChaos: React.FC = () => {
  const frame = useCurrentFrame();

  return (
    <AbsoluteFill style={{ background: COLORS.bgLight }}>
      {/* Pop beat per icon entry */}
      {/* {TOOL_ICONS.map((_, i) => (
        <Sequence key={i} from={i * 3}>
          <Audio src={SFX.mouseClick} volume={0.22} />
        </Sequence>
      ))} */}
      {/* Whoosh on collapse */}
      <Sequence from={75}>
        <Audio src={SFX.whoosh} volume={0.3} />
      </Sequence>
      {TOOL_POSITIONS.map((pos, i) => (
        <ToolIcon
          key={i}
          index={i}
          position={pos}
          iconSrc={TOOL_ICONS[i] || "images/icons/macos/github.webp"}
        />
      ))}
      {/* Problem statement text overlay — appears at frame 35, exits with tool collapse */}
      <div
        style={{
          position: "absolute",
          bottom: 80,
          left: 0,
          right: 0,
          textAlign: "center",
          fontFamily: FONTS.body,
          fontSize: 36,
          fontWeight: 400,
          color: "#71717a",
          opacity: interpolate(frame, [35, 45, 70, 85], [0, 1, 1, 0], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          }),
          pointerEvents: "none",
        }}
      >
        12 tabs. 3 inboxes. 47 unread. It&apos;s 9am.
      </div>
    </AbsoluteFill>
  );
};
