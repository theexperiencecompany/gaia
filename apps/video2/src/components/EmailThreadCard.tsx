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
    config: { damping: 8, stiffness: 180 },
  });
  const opacity = interpolate(cardP, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });
  const scale = interpolate(cardP, [0, 1], [0.88, 1]);

  const highlightP = spring({
    frame: frame - (enterDelay + 6),
    fps,
    config: { damping: 200 },
  });
  const highlightOpacity = interpolate(highlightP, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });

  return (
    <div
      style={{
        width: 1400,
        background: COLORS.surface,
        borderRadius: 32,
        overflow: "hidden",
        transform: `scale(${scale})`,
        opacity,
      }}
    >
      <div
        style={{
          borderLeft: `6px solid ${COLORS.primary}`,
          background: `rgba(0, 187, 255, 0.07)`,
          padding: "32px 44px",
          opacity: highlightOpacity,
        }}
      >
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "flex-start",
            marginBottom: 10,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
            <span
              style={{
                fontFamily: FONTS.body,
                fontSize: 42,
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
                padding: "4px 18px",
                fontFamily: FONTS.body,
                fontSize: 24,
                fontWeight: 700,
              }}
            >
              NEW
            </span>
          </div>
          <span
            style={{
              fontFamily: FONTS.body,
              fontSize: 30,
              color: COLORS.zinc500,
            }}
          >
            {replyTime}
          </span>
        </div>
        <div
          style={{
            fontFamily: FONTS.body,
            fontSize: 36,
            fontWeight: 600,
            color: COLORS.textDark,
            marginBottom: 8,
          }}
        >
          {replySubject}
        </div>
        <div
          style={{
            fontFamily: FONTS.body,
            fontSize: 30,
            color: COLORS.zinc500,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {replyPreview}
        </div>
      </div>

      <div style={{ height: 1, background: COLORS.zinc800 }} />

      <div style={{ padding: "24px 44px", opacity: 0.35 }}>
        <div
          style={{
            fontFamily: FONTS.body,
            fontSize: 34,
            fontWeight: 600,
            color: COLORS.textDark,
            marginBottom: 6,
          }}
        >
          {originalSubject}
        </div>
        <div
          style={{
            fontFamily: FONTS.body,
            fontSize: 28,
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
