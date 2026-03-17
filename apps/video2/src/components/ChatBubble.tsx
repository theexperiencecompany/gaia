import type React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { COLORS, FONTS } from "../constants";

interface ChatBubbleProps {
  message: string;
  timestamp: string;
  delay?: number;
  showCheckmark?: boolean;
  checkmarkDelay?: number;
}

export const ChatBubble: React.FC<ChatBubbleProps> = ({
  message,
  timestamp,
  delay = 0,
  showCheckmark = false,
  checkmarkDelay = 0,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const enterP = spring({
    frame: frame - delay,
    fps,
    config: { damping: 200 },
  });
  const opacity = interpolate(enterP, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });
  const y = interpolate(enterP, [0, 1], [20, 0]);

  const checkP = spring({
    frame: frame - checkmarkDelay,
    fps,
    config: { damping: 200 },
  });
  const checkOpacity = showCheckmark
    ? interpolate(checkP, [0, 0.1], [0, 1], { extrapolateRight: "clamp" })
    : 0;

  return (
    <div
      style={{
        transform: `translateY(${y}px)`,
        opacity,
        display: "flex",
        alignItems: "flex-end",
        gap: 12,
        marginBottom: 18,
      }}
    >
      {/* GAIA avatar dot */}
      <div
        style={{
          width: 36,
          height: 36,
          borderRadius: "50%",
          background: COLORS.primary,
          flexShrink: 0,
          marginBottom: 4,
        }}
      />

      <div style={{ flex: 1 }}>
        {/* Timestamp */}
        <div
          style={{
            fontFamily: FONTS.body,
            fontSize: 20,
            color: COLORS.zinc500,
            marginBottom: 6,
            fontWeight: 400,
          }}
        >
          {timestamp}
        </div>

        {/* Bubble */}
        <div
          style={{
            background: COLORS.surface,
            borderRadius: "40px 40px 40px 8px",
            padding: "24px 32px",
            fontFamily: FONTS.body,
            fontSize: 30,
            fontWeight: 500,
            color: COLORS.textDark,
            lineHeight: 1.45,
            maxWidth: 720,
            display: "inline-block",
          }}
        >
          {message}
        </div>
      </div>

      {/* Checkmark */}
      <div
        style={{
          opacity: checkOpacity,
          width: 36,
          height: 36,
          borderRadius: "50%",
          background: "#22c55e",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          flexShrink: 0,
          marginBottom: 4,
        }}
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
          <path
            d="M3 9l4 4 8-8"
            stroke="white"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </div>
    </div>
  );
};
