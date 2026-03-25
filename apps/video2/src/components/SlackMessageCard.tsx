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
    config: { damping: 8, stiffness: 180 },
  });
  const cardOpacity = interpolate(cardP, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });
  const cardScale = interpolate(cardP, [0, 1], [0.88, 1]);

  return (
    <div
      style={{
        width: 1300,
        background: "#1a1d21",
        borderRadius: 32,
        overflow: "hidden",
        transform: `scale(${cardScale})`,
        opacity: cardOpacity,
      }}
    >
      <div
        style={{
          background: "#19171d",
          padding: "22px 36px",
          display: "flex",
          alignItems: "center",
          gap: 16,
        }}
      >
        <div
          style={{
            width: 40,
            height: 40,
            borderRadius: 10,
            background: "#4a154b",
            flexShrink: 0,
          }}
        />
        <span
          style={{
            fontFamily: FONTS.body,
            fontSize: 34,
            fontWeight: 700,
            color: "#d1d2d3",
          }}
        >
          {workspace}
        </span>
        <span
          style={{
            fontFamily: FONTS.body,
            fontSize: 28,
            color: "#6b6f76",
            marginLeft: 4,
          }}
        >
          · #{channel}
        </span>
      </div>

      <div
        style={{
          padding: "32px 36px",
          display: "flex",
          gap: 20,
        }}
      >
        <div
          style={{
            width: 60,
            height: 60,
            borderRadius: 12,
            background: COLORS.primary,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontFamily: FONTS.display,
            fontSize: 26,
            fontWeight: 700,
            color: "#000",
            flexShrink: 0,
          }}
        >
          G
        </div>

        <div style={{ flex: 1 }}>
          <div
            style={{
              display: "flex",
              alignItems: "baseline",
              gap: 14,
              marginBottom: 10,
            }}
          >
            <span
              style={{
                fontFamily: FONTS.body,
                fontSize: 34,
                fontWeight: 700,
                color: "#d1d2d3",
              }}
            >
              {from}
            </span>
            <span
              style={{
                fontFamily: FONTS.body,
                fontSize: 26,
                color: "#6b6f76",
              }}
            >
              Today at 5:00 AM
            </span>
          </div>
          <div
            style={{
              fontFamily: FONTS.body,
              fontSize: 32,
              color: "#d1d2d3",
              lineHeight: 1.55,
            }}
          >
            {message}
          </div>
        </div>
      </div>
    </div>
  );
};
