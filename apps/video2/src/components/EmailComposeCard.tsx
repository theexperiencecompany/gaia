import type React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { COLORS, FONTS } from "../constants";
import { TypingText } from "./TypingText";

interface EmailComposeCardProps {
  to: string;
  subject: string;
  body: string;
  attachments: string[];
  enterDelay?: number;
  bodyTypingDelay?: number;
  crmStatus?: string;
}

export const EmailComposeCard: React.FC<EmailComposeCardProps> = ({
  to,
  subject,
  body,
  attachments,
  enterDelay = 0,
  bodyTypingDelay = 10,
  crmStatus,
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

  const attachmentStart = bodyTypingDelay + Math.ceil(body.length * 0.5) + 10;
  const crmStart = attachmentStart + attachments.length * 6 + 8;

  const crmP = spring({
    frame: frame - crmStart,
    fps,
    config: { damping: 200 },
  });
  const crmOpacity = crmStatus
    ? interpolate(crmP, [0, 0.1], [0, 1], { extrapolateRight: "clamp" })
    : 0;

  return (
    <div
      style={{
        width: 1500,
        background: COLORS.surface,
        borderRadius: 32,
        overflow: "hidden",
        transform: `scale(${cardScale})`,
        opacity: cardOpacity,
      }}
    >
      <div
        style={{
          padding: "26px 44px",
          background: COLORS.zinc900,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <span
          style={{
            fontFamily: FONTS.body,
            fontSize: 38,
            fontWeight: 700,
            color: COLORS.textDark,
          }}
        >
          New Message
        </span>
        {crmStatus && (
          <div
            style={{
              background: "rgba(34, 197, 94, 0.15)",
              borderRadius: 999,
              padding: "6px 20px",
              fontFamily: FONTS.body,
              fontSize: 26,
              color: "#22c55e",
              opacity: crmOpacity,
            }}
          >
            CRM: {crmStatus}
          </div>
        )}
      </div>

      <div style={{ padding: "24px 44px 0" }}>
        <div
          style={{
            display: "flex",
            gap: 16,
            marginBottom: 18,
            paddingBottom: 18,
            borderBottom: `1px solid ${COLORS.zinc800}`,
          }}
        >
          <span
            style={{
              fontFamily: FONTS.body,
              fontSize: 30,
              color: COLORS.zinc500,
              width: 100,
            }}
          >
            To
          </span>
          <span
            style={{
              fontFamily: FONTS.body,
              fontSize: 32,
              color: COLORS.textDark,
            }}
          >
            {to}
          </span>
        </div>

        <div
          style={{
            display: "flex",
            gap: 16,
            marginBottom: 24,
            paddingBottom: 18,
            borderBottom: `1px solid ${COLORS.zinc800}`,
          }}
        >
          <span
            style={{
              fontFamily: FONTS.body,
              fontSize: 30,
              color: COLORS.zinc500,
              width: 100,
            }}
          >
            Subject
          </span>
          <span
            style={{
              fontFamily: FONTS.body,
              fontSize: 32,
              fontWeight: 600,
              color: COLORS.textDark,
            }}
          >
            {subject}
          </span>
        </div>

        <div style={{ padding: "0 0 24px" }}>
          <TypingText
            text={body}
            framesPerChar={0.5}
            delay={bodyTypingDelay}
            showCursor={false}
            style={{
              fontFamily: FONTS.body,
              fontSize: 30,
              color: COLORS.textDark,
              lineHeight: 1.7,
              whiteSpace: "pre-wrap",
            }}
          />
        </div>
      </div>

      <div
        style={{
          padding: "0 44px 28px",
          display: "flex",
          gap: 12,
          flexWrap: "wrap",
        }}
      >
        {attachments.map((att, i) => {
          const attDelay = attachmentStart + i * 6;
          const attP = spring({
            frame: frame - attDelay,
            fps,
            config: { damping: 200 },
          });
          const attOpacity = interpolate(attP, [0, 0.1], [0, 1], {
            extrapolateRight: "clamp",
          });
          const attScale = interpolate(attP, [0, 1], [0.8, 1]);

          return (
            <div
              key={i}
              style={{
                background: COLORS.zinc900,
                borderRadius: 14,
                padding: "10px 20px",
                display: "flex",
                alignItems: "center",
                gap: 10,
                opacity: attOpacity,
                transform: `scale(${attScale})`,
              }}
            >
              <div
                style={{
                  width: 10,
                  height: 10,
                  borderRadius: 3,
                  background: COLORS.primary,
                  flexShrink: 0,
                }}
              />
              <span
                style={{
                  fontFamily: FONTS.body,
                  fontSize: 26,
                  color: COLORS.zinc400,
                }}
              >
                {att}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
};
