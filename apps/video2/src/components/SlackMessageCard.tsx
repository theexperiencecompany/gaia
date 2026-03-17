import type React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { COLORS, FONTS } from "../constants";

interface SlackMessageCardProps {
  workspace: string;
  channel: string;
  from: string;
  message: string;
  enterDelay?: number;
}

export const SlackMessageCard: React.FC<SlackMessageCardProps> = ({
  workspace,
  channel,
  from,
  message,
  enterDelay = 0,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const cardP = spring({
    frame: frame - enterDelay,
    fps,
    config: { damping: 22, stiffness: 100 },
  });
  const cardOpacity = interpolate(cardP, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });
  const cardY = interpolate(cardP, [0, 1], [40, 0]);
  const cardScale = interpolate(cardP, [0, 1], [0.94, 1]);

  return (
    <div
      style={{
        width: 760,
        background: "#1a1d21",
        borderRadius: 28,
        border: "1px solid #2d2d2d",
        overflow: "hidden",
        transform: `translateY(${cardY}px) scale(${cardScale})`,
        opacity: cardOpacity,
      }}
    >
      {/* Workspace header */}
      <div
        style={{
          background: "#19171d",
          padding: "16px 24px",
          display: "flex",
          alignItems: "center",
          gap: 12,
          borderBottom: "1px solid #2d2d2d",
        }}
      >
        <div
          style={{
            width: 28,
            height: 28,
            borderRadius: 8,
            background: "#4a154b",
            flexShrink: 0,
          }}
        />
        <span
          style={{
            fontFamily: FONTS.body,
            fontSize: 22,
            fontWeight: 700,
            color: "#d1d2d3",
          }}
        >
          {workspace}
        </span>
        <span
          style={{
            fontFamily: FONTS.body,
            fontSize: 20,
            color: "#6b6f76",
            marginLeft: 4,
          }}
        >
          · #{channel}
        </span>
      </div>

      {/* Message */}
      <div
        style={{
          padding: "20px 24px",
          display: "flex",
          gap: 14,
        }}
      >
        {/* GAIA avatar */}
        <div
          style={{
            width: 44,
            height: 44,
            borderRadius: 8,
            background: COLORS.primary,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontFamily: FONTS.display,
            fontSize: 18,
            fontWeight: 700,
            color: "#000",
            flexShrink: 0,
          }}
        >
          G
        </div>

        <div style={{ flex: 1 }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 6 }}>
            <span
              style={{
                fontFamily: FONTS.body,
                fontSize: 24,
                fontWeight: 700,
                color: "#d1d2d3",
              }}
            >
              {from}
            </span>
            <span
              style={{
                fontFamily: FONTS.body,
                fontSize: 18,
                color: "#6b6f76",
              }}
            >
              Today at 5:00 AM
            </span>
          </div>
          <div
            style={{
              fontFamily: FONTS.body,
              fontSize: 24,
              color: "#d1d2d3",
              lineHeight: 1.5,
            }}
          >
            {message}
          </div>
        </div>
      </div>
    </div>
  );
};
