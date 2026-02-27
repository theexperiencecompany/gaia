import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig, spring, interpolate, Img, staticFile } from "remotion";
import { COLORS, FONTS } from "../constants";

const BRIEFING_LINES = [
  "Good morning! Here's your briefing:",
  "",
  "• 12 new emails (3 need replies)",
  "• Design review meeting at 2 PM",
  "• Vendor invoice: follow up needed",
  "• Q4 report from Sarah awaiting review",
];

export const S24_NotificationPreview: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Card scales in
  const cardProgress = spring({ frame, fps, config: { damping: 22, stiffness: 100 } });
  const cardScale = interpolate(cardProgress, [0, 1], [0.8, 1.0]);
  const cardOpacity = interpolate(cardProgress, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });

  return (
    <AbsoluteFill
      style={{
        background: COLORS.bgLight,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <div
        style={{
          background: "rgba(25, 25, 28, 0.97)",
          borderRadius: 28,
          border: "1px solid rgba(255,255,255,0.12)",
          padding: "44px 56px",
          width: 1100,
          transform: `scale(${cardScale})`,
          opacity: cardOpacity,
        }}
      >
        {/* Header */}
        <div style={{ display: "flex", alignItems: "center", gap: 20, marginBottom: 32 }}>
          <div style={{ width: 96, height: 96, borderRadius: 20, overflow: "hidden", flexShrink: 0 }}>
            <Img src={staticFile("images/icons/macos/telegram.webp")} style={{ width: 96, height: 96, objectFit: "cover" }} />
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
              <span style={{ color: "#a1a1aa", fontSize: 26, fontFamily: FONTS.body, fontWeight: 600 }}>
                Telegram
              </span>
              <span style={{ color: "#71717a", fontSize: 22, fontFamily: FONTS.body }}>now</span>
            </div>
            <div style={{ color: "white", fontSize: 34, fontFamily: FONTS.body, fontWeight: 700 }}>
              GAIA • Daily Email Digest
            </div>
          </div>
        </div>

        {/* Briefing content */}
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {BRIEFING_LINES.map((line, i) => {
            const lineProgress = spring({
              frame: frame - i * 8 - 15,
              fps,
              config: { damping: 200 },
            });
            const lineOpacity = interpolate(lineProgress, [0, 0.1], [0, 1], {
              extrapolateRight: "clamp",
            });
            const lineY = interpolate(lineProgress, [0, 1], [10, 0]);

            if (!line) return <div key={i} style={{ height: 8 }} />;

            return (
              <div
                key={i}
                style={{
                  color: "white",
                  fontSize: 28,
                  fontFamily: FONTS.body,
                  lineHeight: 1.5,
                  opacity: lineOpacity,
                  transform: `translateY(${lineY}px)`,
                }}
              >
                {line}
              </div>
            );
          })}
        </div>

        {/* CTA */}
        <div
          style={{
            marginTop: 32,
            padding: "14px 28px",
            borderRadius: 14,
            border: `1px solid ${COLORS.primary}66`,
            color: COLORS.primary,
            fontSize: 24,
            fontFamily: FONTS.body,
            fontWeight: 600,
            display: "inline-flex",
            alignItems: "center",
            gap: 8,
            boxShadow: `0 0 12px ${COLORS.primary}22`,
          }}
        >
          View in Telegram →
        </div>
      </div>
    </AbsoluteFill>
  );
};
