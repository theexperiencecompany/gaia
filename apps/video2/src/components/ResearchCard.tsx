import type React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { COLORS, FONTS } from "../constants";

interface ResearchItem {
  label: string;
  value: string;
}

interface ResearchCardProps {
  vcName: string;
  fund: string;
  focus: string;
  items: ResearchItem[];
  enterDelay?: number;
}

export const ResearchCard: React.FC<ResearchCardProps> = ({
  vcName,
  fund,
  focus,
  items,
  enterDelay = 0,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const cardP = spring({
    frame: frame - enterDelay,
    fps,
    config: { damping: 22, stiffness: 100 },
  });
  const opacity = interpolate(cardP, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });
  const y = interpolate(cardP, [0, 1], [50, 0]);
  const scale = interpolate(cardP, [0, 1], [0.94, 1]);

  return (
    <div
      style={{
        width: 900,
        background: COLORS.surface,
        borderRadius: 28,
        padding: "40px 48px",
        transform: `translateY(${y}px) scale(${scale})`,
        opacity,
      }}
    >
      {/* Header */}
      <div style={{ marginBottom: 24 }}>
        <div
          style={{
            fontFamily: FONTS.display,
            fontSize: 44,
            fontWeight: 700,
            color: COLORS.textDark,
            lineHeight: 1.1,
            marginBottom: 8,
          }}
        >
          {vcName}
        </div>
        <div
          style={{
            fontFamily: FONTS.body,
            fontSize: 26,
            fontWeight: 600,
            color: COLORS.primary,
            marginBottom: 4,
          }}
        >
          {fund}
        </div>
        <div
          style={{
            fontFamily: FONTS.body,
            fontSize: 24,
            color: COLORS.zinc400,
          }}
        >
          {focus}
        </div>
      </div>

      {/* Divider */}
      <div style={{ height: 1, background: COLORS.zinc700, marginBottom: 24 }} />

      {/* Items */}
      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        {items.map((item, i) => {
          const itemDelay = enterDelay + 15 + i * 12;
          const itemP = spring({
            frame: frame - itemDelay,
            fps,
            config: { damping: 200 },
          });
          const itemOpacity = interpolate(itemP, [0, 0.1], [0, 1], {
            extrapolateRight: "clamp",
          });
          const itemY = interpolate(itemP, [0, 1], [15, 0]);

          return (
            <div
              key={i}
              style={{
                display: "flex",
                alignItems: "flex-start",
                gap: 14,
                transform: `translateY(${itemY}px)`,
                opacity: itemOpacity,
              }}
            >
              <div
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: "50%",
                  background: COLORS.primary,
                  marginTop: 8,
                  flexShrink: 0,
                }}
              />
              <div style={{ flex: 1 }}>
                <span
                  style={{
                    fontFamily: FONTS.body,
                    fontSize: 24,
                    fontWeight: 600,
                    color: COLORS.zinc400,
                  }}
                >
                  {item.label}:{" "}
                </span>
                <span
                  style={{
                    fontFamily: FONTS.body,
                    fontSize: 24,
                    color: COLORS.textDark,
                  }}
                >
                  {item.value}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
