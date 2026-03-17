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
    config: { damping: 22, stiffness: 100 },
  });
  const cardOpacity = interpolate(cardP, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });
  const cardY = interpolate(cardP, [0, 1], [40, 0]);
  const cardScale = interpolate(cardP, [0, 1], [0.95, 1]);

  // Attachments appear after body finishes typing
  const attachmentStart = bodyTypingDelay + Math.ceil(body.length * 0.5) + 10;
  const crmStart = attachmentStart + attachments.length * 6 + 10;

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
        width: 860,
        background: COLORS.surface,
        borderRadius: 28,
        overflow: "hidden",
        transform: `translateY(${cardY}px) scale(${cardScale})`,
        opacity: cardOpacity,
      }}
    >
      {/* Header */}
      <div
        style={{
          padding: "18px 28px",
          borderBottom: `1px solid ${COLORS.zinc700}`,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <span
          style={{
            fontFamily: FONTS.body,
            fontSize: 26,
            fontWeight: 700,
            color: COLORS.textDark,
          }}
        >
          New Message
        </span>
        {crmStatus && (
          <div
            style={{
              background: "rgba(34, 197, 94, 0.13)",
              border: "1px solid #22c55e",
              borderRadius: 999,
              padding: "4px 14px",
              fontFamily: FONTS.body,
              fontSize: 20,
              color: "#22c55e",
              opacity: crmOpacity,
            }}
          >
            CRM: {crmStatus}
          </div>
        )}
      </div>

      {/* Fields */}
      <div style={{ padding: "16px 28px 0" }}>
        {/* To */}
        <div
          style={{
            display: "flex",
            gap: 12,
            marginBottom: 12,
            borderBottom: `1px solid ${COLORS.zinc700}`,
            paddingBottom: 12,
          }}
        >
          <span style={{ fontFamily: FONTS.body, fontSize: 22, color: COLORS.zinc500, width: 80 }}>To</span>
          <span style={{ fontFamily: FONTS.body, fontSize: 24, color: COLORS.textDark }}>{to}</span>
        </div>

        {/* Subject */}
        <div
          style={{
            display: "flex",
            gap: 12,
            marginBottom: 16,
            borderBottom: `1px solid ${COLORS.zinc700}`,
            paddingBottom: 12,
          }}
        >
          <span style={{ fontFamily: FONTS.body, fontSize: 22, color: COLORS.zinc500, width: 80 }}>Subject</span>
          <span style={{ fontFamily: FONTS.body, fontSize: 24, fontWeight: 600, color: COLORS.textDark }}>{subject}</span>
        </div>

        {/* Body */}
        <div style={{ padding: "0 0 16px" }}>
          <TypingText
            text={body}
            framesPerChar={0.5}
            delay={bodyTypingDelay}
            showCursor={false}
            style={{
              fontFamily: FONTS.body,
              fontSize: 24,
              color: COLORS.textDark,
              lineHeight: 1.65,
              whiteSpace: "pre-wrap",
            }}
          />
        </div>
      </div>

      {/* Attachments */}
      <div
        style={{
          padding: "0 28px 20px",
          display: "flex",
          gap: 10,
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
                borderRadius: 12,
                padding: "8px 14px",
                display: "flex",
                alignItems: "center",
                gap: 8,
                opacity: attOpacity,
                transform: `scale(${attScale})`,
              }}
            >
              <div
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: 2,
                  background: COLORS.primary,
                  flexShrink: 0,
                }}
              />
              <span
                style={{
                  fontFamily: FONTS.body,
                  fontSize: 20,
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
