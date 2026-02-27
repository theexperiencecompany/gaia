import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig, spring, interpolate } from "remotion";
import { COLORS, FONTS } from "../constants";
import { PlatformIcon } from "../components/PlatformIcon";

const PLATFORMS = [
  { src: "images/icons/macos/telegram.webp", label: "Telegram", delay: 0, comingSoon: false },
  { src: "images/icons/macos/discord.webp", label: "Discord", delay: 8, comingSoon: false },
  { src: "images/icons/macos/slack.webp", label: "Slack", delay: 16, comingSoon: false },
  { src: "images/icons/macos/whatsapp.webp", label: "WhatsApp", delay: 24, comingSoon: true },
];

export const S23_PlatformIcons: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // "GAIA meets you where you are." — appears at frame 60
  const textProgress = spring({ frame: frame - 60, fps, config: { damping: 15 } });
  const textBlur = interpolate(textProgress, [0, 1], [20, 0]);
  const textScale = interpolate(textProgress, [0, 1], [0.95, 1.0]);
  const textOpacity = interpolate(textProgress, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });

  return (
    <AbsoluteFill
      style={{
        background: COLORS.bgLight,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 80,
      }}
    >
      {/* Headline text */}
      {frame >= 60 && (
        <div
          style={{
            fontFamily: FONTS.display,
            fontSize: 80,
            fontWeight: 800,
            color: COLORS.textDark,
            textAlign: "center",
            filter: `blur(${textBlur}px)`,
            transform: `scale(${textScale})`,
            opacity: textOpacity,
          }}
        >
          GAIA meets you where you are.
        </div>
      )}

      {/* Platform icons row */}
      <div
        style={{
          display: "flex",
          alignItems: "flex-end",
          gap: 60,
        }}
      >
        {PLATFORMS.map((platform, i) => (
          <PlatformIcon
            key={i}
            src={platform.src}
            label={platform.label}
            delay={platform.delay}
            size={120}
            iconIndex={i}
            comingSoon={platform.comingSoon}
            textColor={COLORS.textDark}
          />
        ))}
      </div>
    </AbsoluteFill>
  );
};
