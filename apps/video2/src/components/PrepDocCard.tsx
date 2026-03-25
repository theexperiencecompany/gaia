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

  const titleP = spring({
    frame: frame - enterDelay,
    fps,
    config: { damping: 200 },
  });
  const titleOpacity = interpolate(titleP, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });
  const titleY = interpolate(titleP, [0, 1], [20, 0]);

  return (
    <div style={{ width: 1500 }}>
      <div
        style={{
          fontFamily: FONTS.display,
          fontSize: 44,
          fontWeight: 700,
          color: COLORS.zinc400,
          marginBottom: 28,
          opacity: titleOpacity,
          transform: `translateY(${titleY}px)`,
          display: "flex",
          alignItems: "center",
          gap: 16,
        }}
      >
        <div
          style={{
            width: 36,
            height: 36,
            borderRadius: 8,
            background: "#4285f4",
            flexShrink: 0,
          }}
        />
        {title}
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 24,
        }}
      >
        {questions.map((q, i) => {
          const cardDelay = enterDelay + 12 + i * 14;
          const cardP = spring({
            frame: frame - cardDelay,
            fps,
            config: { damping: 8, stiffness: 180 },
          });
          const cardOpacity = interpolate(cardP, [0, 0.1], [0, 1], {
            extrapolateRight: "clamp",
          });
          const cardScale = interpolate(cardP, [0, 1], [0.88, 1]);

          return (
            <div
              key={i}
              style={{
                background: COLORS.surface,
                borderRadius: 28,
                padding: "40px 44px",
                transform: `scale(${cardScale})`,
                opacity: cardOpacity,
              }}
            >
              <div
                style={{
                  fontFamily: FONTS.body,
                  fontSize: 30,
                  fontWeight: 700,
                  color: COLORS.textDark,
                  marginBottom: 16,
                  lineHeight: 1.3,
                }}
              >
                {i + 1}. {q.question}
              </div>
              <div
                style={{
                  fontFamily: FONTS.body,
                  fontSize: 26,
                  color: COLORS.zinc400,
                  lineHeight: 1.55,
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
