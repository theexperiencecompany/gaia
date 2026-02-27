import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig, spring, interpolate, Img, staticFile } from "remotion";
import { COLORS, FONTS } from "../constants";
import { SceneBackground } from "../components/SceneBackground";
import { BotTail } from "./S06_UserChat";

const FULL_MESSAGE = `Your Daily Email Digest is ready.

12 emails. Key highlights:
→ Reply needed: Sarah's Q4 report request
→ Meeting confirmed: Design review at 2 PM
→ Action: Follow up on vendor invoice

Posted to #daily-briefing in Slack.`;

export const S19_BotMessageStream: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Stream chars at 1 per 1.5 frames
  const charIndex = Math.min(Math.floor(frame / 1.5), FULL_MESSAGE.length);
  const displayText = FULL_MESSAGE.slice(0, charIndex);
  const cursorOpacity = Math.floor(frame / 10) % 2 === 0 ? 1 : 0;

  // Bubble entrance
  const enterProgress = spring({ frame, fps, config: { damping: 25 } });
  const enterY = interpolate(enterProgress, [0, 1], [30, 0]);
  const enterOpacity = interpolate(enterProgress, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });

  return (
    <AbsoluteFill>
      <SceneBackground variant="light" />
      <div
        style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <div style={{ width: 1400, display: "flex", flexDirection: "column", gap: 28 }}>
          {/* GAIA bot message */}
          <div
            style={{
              display: "flex",
              alignItems: "flex-start",
              gap: 20,
              paddingLeft: 8,
              transform: `translateY(${enterY}px)`,
              opacity: enterOpacity,
            }}
          >
            <Img
              src={staticFile("images/logos/logo.webp")}
              style={{ width: 60, height: 60, borderRadius: "50%", objectFit: "contain", flexShrink: 0, marginTop: 4 }}
            />
            <div style={{ position: "relative" }}>
              <div
                style={{
                  background: "#27272a",
                  color: "white",
                  padding: "18px 32px",
                  borderRadius: 28,
                  fontSize: 30,
                  lineHeight: 1.65,
                  fontFamily: FONTS.body,
                  whiteSpace: "pre-wrap",
                  maxWidth: 1100,
                }}
              >
                {displayText}
                <span
                  style={{
                    display: "inline-block",
                    width: 2,
                    height: "1em",
                    background: COLORS.primary,
                    marginLeft: 3,
                    verticalAlign: "text-bottom",
                    opacity: charIndex < FULL_MESSAGE.length ? cursorOpacity : 0,
                  }}
                />
              </div>
              <BotTail bgColor={COLORS.bgLight} />
            </div>
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};
