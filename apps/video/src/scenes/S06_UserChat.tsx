import React from "react";
import {
  AbsoluteFill,
  useCurrentFrame,
  useVideoConfig,
  spring,
  interpolate,
  Img,
  staticFile,
} from "remotion";
import { COLORS, FONTS } from "../constants";
import { TypingText } from "../components/TypingText";

const USER_MESSAGE =
  "Hey GAIA — pull my Gmail from the last 6 hours, check Google Calendar for today's meetings, scan my GitHub for open PRs, and check Slack for anything urgent. Summarize everything and set this up to run every morning at 8am automatically.";

// iMessage tail — user bubble (bottom-right)
export const UserTail: React.FC<{ bg?: string; bgColor?: string }> = ({ bg = COLORS.primary, bgColor = COLORS.bg }) => (
  <>
    <div style={{ position: "absolute", bottom: 0, right: -7, width: 20, height: 18, background: bg, borderBottomLeftRadius: "16px 14px" }} />
    <div style={{ position: "absolute", bottom: 0, right: -26, width: 26, height: 18, background: bgColor, borderBottomLeftRadius: 10 }} />
  </>
);

// iMessage tail — bot bubble (bottom-left)
export const BotTail: React.FC<{ bgColor?: string }> = ({ bgColor = COLORS.bg }) => (
  <>
    <div style={{ position: "absolute", bottom: 0, left: -7, width: 20, height: 18, background: "#27272a", borderBottomRightRadius: 16 }} />
    <div style={{ position: "absolute", bottom: 0, left: -26, width: 26, height: 18, background: bgColor, borderBottomRightRadius: 10 }} />
  </>
);

export const S06_UserChat: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Whole scene fades in
  const sceneProgress = spring({ frame, fps, config: { damping: 25 } });
  const sceneOpacity = interpolate(sceneProgress, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });

  const typingDone = frame >= Math.ceil(USER_MESSAGE.length / 2);

  // Typing indicator after message completes
  const indicatorDelay = Math.ceil(USER_MESSAGE.length / 2) + 8;
  const indicatorProgress = spring({ frame: frame - indicatorDelay, fps, config: { damping: 25 } });
  const indicatorOpacity = interpolate(indicatorProgress, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });

  const dot1 = interpolate(Math.sin(((frame - indicatorDelay) / 12) * Math.PI * 2), [-1, 1], [0.3, 1.0]);
  const dot2 = interpolate(Math.sin(((frame - indicatorDelay - 4) / 12) * Math.PI * 2), [-1, 1], [0.3, 1.0]);
  const dot3 = interpolate(Math.sin(((frame - indicatorDelay - 8) / 12) * Math.PI * 2), [-1, 1], [0.3, 1.0]);

  return (
    <AbsoluteFill style={{ background: COLORS.bgLight, display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div
        style={{
          width: 1400,
          display: "flex",
          flexDirection: "column",
          gap: 32,
          opacity: sceneOpacity,
          paddingBottom: 40,
        }}
      >
        {/* User message bubble — right aligned */}
        <div style={{ display: "flex", justifyContent: "flex-end", paddingRight: 32 }}>
          <div style={{ position: "relative", maxWidth: "85%" }}>
            <div
              style={{
                background: COLORS.primary,
                color: "#000",
                padding: "18px 36px",
                borderRadius: "40px 40px 8px 40px",
                fontSize: 34,
                lineHeight: 1.55,
                fontWeight: 500,
                fontFamily: FONTS.body,
              }}
            >
              <TypingText
                text={USER_MESSAGE}
                framesPerChar={0.5}
                delay={0}
                cursorColor="#000000"
                showCursor={!typingDone}
                style={{ display: "block" }}
              />
            </div>
            <UserTail bg={COLORS.primary} bgColor={COLORS.bgLight} />
          </div>
        </div>

        {/* GAIA typing indicator */}
        {frame >= indicatorDelay && (
          <div style={{ display: "flex", alignItems: "flex-end", gap: 18, paddingLeft: 8, opacity: indicatorOpacity }}>
            <Img
              src={staticFile("images/logos/logo.webp")}
              style={{ width: 60, height: 60, borderRadius: "50%", objectFit: "contain", flexShrink: 0 }}
            />
            <div style={{ background: "#27272a", padding: "20px 32px", borderRadius: "40px 40px 40px 8px", position: "relative", display: "flex", gap: 12, alignItems: "center" }}>
              {[dot1, dot2, dot3].map((d, i) => (
                <div key={i} style={{ width: 14, height: 14, borderRadius: "50%", background: COLORS.zinc400, opacity: d }} />
              ))}
              <BotTail bgColor={COLORS.bgLight} />
            </div>
          </div>
        )}
      </div>
    </AbsoluteFill>
  );
};
