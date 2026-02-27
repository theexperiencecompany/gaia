import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig, spring, interpolate, Img, staticFile } from "remotion";
import { COLORS, FONTS } from "../constants";
import { SceneBackground } from "../components/SceneBackground";
import { UserTail, BotTail } from "./S06_UserChat";

const BOT_MESSAGE = `Your Daily Email Digest is ready.

12 emails. Key highlights:
→ Reply needed: Sarah's Q4 report request
→ Meeting confirmed: Design review at 2 PM
→ Action: Follow up on vendor invoice

Posted to #daily-briefing in Slack.`;

export const S20_iMessageBriefing: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // User bubble entrance
  const userProgress = spring({ frame, fps, config: { damping: 25 } });
  const userOpacity = interpolate(userProgress, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });
  const userY = interpolate(userProgress, [0, 1], [20, 0]);

  // Bot bubble entrance after user
  const botProgress = spring({ frame: frame - 20, fps, config: { damping: 25 } });
  const botOpacity = interpolate(botProgress, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });
  const botY = interpolate(botProgress, [0, 1], [20, 0]);

  // Success toast slides in from below
  const toastProgress = spring({ frame: frame - 35, fps, config: { damping: 25 } });
  const toastY = interpolate(toastProgress, [0, 1], [40, 0]);
  const toastOpacity = interpolate(toastProgress, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });

  return (
    <AbsoluteFill>
      <SceneBackground variant="solid" />
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
          {/* User trigger bubble */}
          <div
            style={{
              display: "flex",
              justifyContent: "flex-end",
              paddingRight: 8,
              opacity: userOpacity,
              transform: `translateY(${userY}px)`,
            }}
          >
            <div style={{ position: "relative" }}>
              <div
                style={{
                  background: COLORS.primary,
                  color: "#000",
                  padding: "14px 28px",
                  borderRadius: 28,
                  fontSize: 32,
                  fontWeight: 600,
                  fontFamily: FONTS.body,
                }}
              >
                Run Daily Email Digest
              </div>
              <UserTail bg={COLORS.primary} />
            </div>
          </div>

          {/* GAIA briefing reply */}
          <div
            style={{
              display: "flex",
              alignItems: "flex-start",
              gap: 20,
              paddingLeft: 8,
              opacity: botOpacity,
              transform: `translateY(${botY}px)`,
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
                {BOT_MESSAGE}
              </div>
              <BotTail />
            </div>
          </div>

          {/* Success toast */}
          <div
            style={{
              display: "flex",
              justifyContent: "center",
              opacity: toastOpacity,
              transform: `translateY(${toastY}px)`,
            }}
          >
            <div
              style={{
                background: "#18181b",
                borderRadius: 16,
                padding: "14px 28px",
                display: "flex",
                alignItems: "center",
                gap: 14,
              }}
            >
              <span style={{ color: "#22c55e", fontSize: 32 }}>✓</span>
              <div>
                <div style={{ color: "white", fontFamily: FONTS.body, fontSize: 26, fontWeight: 600 }}>
                  Workflow ran successfully
                </div>
                <div style={{ color: COLORS.zinc500, fontFamily: FONTS.body, fontSize: 22 }}>
                  in 3.2s · 4 tools used
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};
