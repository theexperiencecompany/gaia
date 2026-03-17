import type React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { COLORS, FONTS } from "../constants";

interface Question {
  question: string;
  talkingPoint: string;
}

interface PrepDocCardProps {
  title: string;
  questions: Question[];
  enterDelay?: number;
}

export const PrepDocCard: React.FC<PrepDocCardProps> = ({
  title,
  questions,
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
  const cardScale = interpolate(cardP, [0, 1], [0.95, 1]);

  return (
    <div
      style={{
        width: 860,
        background: "#1c1c1e",
        borderRadius: 28,
        border: `1px solid ${COLORS.zinc700}`,
        overflow: "hidden",
        transform: `translateY(${cardY}px) scale(${cardScale})`,
        opacity: cardOpacity,
      }}
    >
      {/* Doc header */}
      <div
        style={{
          background: COLORS.surface,
          padding: "20px 28px",
          display: "flex",
          alignItems: "center",
          gap: 14,
          borderBottom: `1px solid ${COLORS.zinc700}`,
        }}
      >
        <div
          style={{
            width: 32,
            height: 32,
            borderRadius: 8,
            background: "#4285f4",
            flexShrink: 0,
          }}
        />
        <span
          style={{
            fontFamily: FONTS.body,
            fontSize: 24,
            fontWeight: 600,
            color: COLORS.textDark,
          }}
        >
          {title}
        </span>
      </div>

      {/* Questions */}
      <div style={{ padding: "24px 28px", display: "flex", flexDirection: "column", gap: 24 }}>
        {questions.map((q, i) => {
          const qDelay = enterDelay + 15 + i * 18;
          const tpDelay = qDelay + 8;

          const qP = spring({
            frame: frame - qDelay,
            fps,
            config: { damping: 200 },
          });
          const qOpacity = interpolate(qP, [0, 0.1], [0, 1], {
            extrapolateRight: "clamp",
          });
          const qY = interpolate(qP, [0, 1], [12, 0]);

          const tpP = spring({
            frame: frame - tpDelay,
            fps,
            config: { damping: 200 },
          });
          const tpOpacity = interpolate(tpP, [0, 0.1], [0, 1], {
            extrapolateRight: "clamp",
          });

          return (
            <div key={i}>
              <div
                style={{
                  fontFamily: FONTS.body,
                  fontSize: 24,
                  fontWeight: 700,
                  color: COLORS.textDark,
                  marginBottom: 8,
                  transform: `translateY(${qY}px)`,
                  opacity: qOpacity,
                }}
              >
                {i + 1}. {q.question}
              </div>
              <div
                style={{
                  fontFamily: FONTS.body,
                  fontSize: 22,
                  color: COLORS.zinc400,
                  paddingLeft: 20,
                  borderLeft: `3px solid ${COLORS.zinc700}`,
                  lineHeight: 1.5,
                  opacity: tpOpacity,
                }}
              >
                {q.talkingPoint}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
