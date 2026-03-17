import type React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { COLORS, FONTS } from "../constants";
import { ChatBubble } from "./ChatBubble";

export interface ThreadMessage {
  message: string;
  timestamp: string;
  delay: number;
  showCheckmark?: boolean;
  checkmarkDelay?: number;
}

interface ChatThreadProps {
  messages: ThreadMessage[];
  appName?: string;
  contactName?: string;
  enterDelay?: number;
}

export const ChatThread: React.FC<ChatThreadProps> = ({
  messages,
  appName = "Telegram",
  contactName = "GAIA",
  enterDelay = 0,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const containerP = spring({
    frame: frame - enterDelay,
    fps,
    config: { damping: 200 },
  });
  const containerOpacity = interpolate(containerP, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });

  return (
    <div
      style={{
        width: 900,
        borderRadius: 40,
        border: `1px solid ${COLORS.zinc700}`,
        overflow: "hidden",
        opacity: containerOpacity,
      }}
    >
      {/* Header */}
      <div
        style={{
          background: COLORS.surface,
          padding: "20px 28px",
          display: "flex",
          alignItems: "center",
          gap: 16,
          borderBottom: `1px solid ${COLORS.zinc700}`,
        }}
      >
        {/* Avatar */}
        <div
          style={{
            width: 52,
            height: 52,
            borderRadius: "50%",
            background: COLORS.primary,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontFamily: FONTS.display,
            fontSize: 22,
            fontWeight: 700,
            color: "#000",
            flexShrink: 0,
          }}
        >
          G
        </div>
        <div>
          <div
            style={{
              fontFamily: FONTS.body,
              fontSize: 28,
              fontWeight: 700,
              color: COLORS.textDark,
              lineHeight: 1.2,
            }}
          >
            {contactName}
          </div>
          <div
            style={{
              fontFamily: FONTS.body,
              fontSize: 20,
              color: COLORS.zinc500,
              marginTop: 2,
            }}
          >
            {appName}
          </div>
        </div>
      </div>

      {/* Messages */}
      <div
        style={{
          background: COLORS.bg,
          padding: "24px 30px 18px",
        }}
      >
        {messages.map((msg, i) => (
          <ChatBubble
            key={i}
            message={msg.message}
            timestamp={msg.timestamp}
            delay={msg.delay}
            showCheckmark={msg.showCheckmark}
            checkmarkDelay={msg.checkmarkDelay}
          />
        ))}
      </div>
    </div>
  );
};
