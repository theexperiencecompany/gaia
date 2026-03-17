import type React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { COLORS, FONTS } from "../constants";

interface EmailThreadCardProps {
  replyFrom: string;
  replySubject: string;
  replyPreview: string;
  replyTime: string;
  originalSubject: string;
  originalPreview: string;
  enterDelay?: number;
}

export const EmailThreadCard: React.FC<EmailThreadCardProps> = ({
  replyFrom,
  replySubject,
  replyPreview,
  replyTime,
  originalSubject,
  originalPreview,
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
  const y = interpolate(cardP, [0, 1], [40, 0]);
  const scale = interpolate(cardP, [0, 1], [0.95, 1]);

  const highlightP = spring({
    frame: frame - (enterDelay + 10),
    fps,
    config: { damping: 200 },
  });
  const highlightOpacity = interpolate(highlightP, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });

  return (
    <div
      style={{
        width: 860,
        background: COLORS.surface,
        borderRadius: 28,
        overflow: "hidden",
        transform: `translateY(${y}px) scale(${scale})`,
        opacity,
      }}
    >
      {/* Reply row — highlighted */}
      <div
        style={{
          borderLeft: `4px solid ${COLORS.primary}`,
          background: `rgba(0, 187, 255, 0.06)`,
          padding: "20px 28px",
          opacity: highlightOpacity,
        }}
      >
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "flex-start",
            marginBottom: 6,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <span
              style={{
                fontFamily: FONTS.body,
                fontSize: 26,
                fontWeight: 700,
                color: COLORS.textDark,
              }}
            >
              {replyFrom}
            </span>
            <span
              style={{
                background: COLORS.primary,
                color: "#000",
                borderRadius: 999,
                padding: "3px 12px",
                fontFamily: FONTS.body,
                fontSize: 18,
                fontWeight: 700,
              }}
            >
              NEW
            </span>
          </div>
          <span
            style={{
              fontFamily: FONTS.body,
              fontSize: 22,
              color: COLORS.zinc500,
            }}
          >
            {replyTime}
          </span>
        </div>
        <div
          style={{
            fontFamily: FONTS.body,
            fontSize: 24,
            fontWeight: 600,
            color: COLORS.textDark,
            marginBottom: 4,
          }}
        >
          {replySubject}
        </div>
        <div
          style={{
            fontFamily: FONTS.body,
            fontSize: 22,
            color: COLORS.zinc500,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {replyPreview}
        </div>
      </div>

      {/* Divider */}
      <div style={{ height: 1, background: COLORS.zinc700 }} />

      {/* Original email — muted */}
      <div style={{ padding: "16px 28px", opacity: 0.4 }}>
        <div
          style={{
            fontFamily: FONTS.body,
            fontSize: 24,
            fontWeight: 600,
            color: COLORS.textDark,
            marginBottom: 4,
          }}
        >
          {originalSubject}
        </div>
        <div
          style={{
            fontFamily: FONTS.body,
            fontSize: 22,
            color: COLORS.zinc500,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {originalPreview}
        </div>
      </div>
    </div>
  );
};
