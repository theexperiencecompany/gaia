import React from "react";
import {
  AbsoluteFill,
  Audio,
  Sequence,
  useCurrentFrame,
  useVideoConfig,
  spring,
  interpolate,
  Img,
  staticFile,
} from "remotion";
import { COLORS, FONTS } from "../constants";
import { SFX } from "../sfx";
import { TypingText } from "../components/TypingText";
import { UserTail, BotTail } from "./S06_UserChat";
import { WorkflowDraftVideoCard } from "../components/WorkflowDraftVideoCard";

const USER_MESSAGE =
  "Hey GAIA — pull my Gmail from the last 6 hours, check Google Calendar for today's meetings, scan my GitHub for open PRs, and check Slack for anything urgent. Summarize everything and set this up to run every morning at 8am automatically.";

const BOT_MESSAGE =
  "14 emails (3 need replies). Vendor invoice due Friday.\n3 meetings today. 2 overnight PRs. 3 urgent Slack DMs.\n\nWorkflow created — runs every morning at 8am.";

export const S08_ChatResponse: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const bubbleProgress = spring({ frame, fps, config: { damping: 25 } });
  const bubbleOpacity = interpolate(bubbleProgress, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });
  const bubbleY = interpolate(bubbleProgress, [0, 1], [24, 0]);

  const streamingFrames = Math.ceil(BOT_MESSAGE.length * 0.7); // framesPerChar≈0.7
  const messageComplete = frame >= streamingFrames;
  const cardDelay = Math.ceil(BOT_MESSAGE.length * 0.7 * 0.55);
  const cardProgress = spring({ frame: frame - cardDelay, fps, config: { damping: 22, stiffness: 100 } });
  const cardOpacity = interpolate(cardProgress, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });
  const cardY = interpolate(cardProgress, [0, 1], [40, 0]);
  const cardScale = interpolate(cardProgress, [0, 1], [0.92, 1.0]);

  return (
    <AbsoluteFill style={{ background: COLORS.bgLight, display: "flex", alignItems: "center", justifyContent: "center" }}>
      {/* Rapid mouse-click pulses simulating the bot streaming its response */}
      {Array.from({ length: Math.ceil(streamingFrames / 5) }).map((_, i) => (
        <Sequence key={i} from={i * 5} durationInFrames={5}>
          <Audio src={SFX.mouseClick} volume={0.13} />
        </Sequence>
      ))}
      <div style={{ width: 1400, display: "flex", flexDirection: "column", gap: 32 }}>

        {/* User message (faded context) */}
        <div style={{ display: "flex", justifyContent: "flex-end", paddingRight: 32, opacity: 0.4 }}>
          <div style={{ position: "relative" }}>
            <div style={{ background: COLORS.primary, color: "#000", padding: "12px 24px", borderRadius: "40px 40px 8px 40px", fontSize: 24, lineHeight: 1.5, fontWeight: 500, fontFamily: FONTS.body, maxWidth: 900 }}>
              {USER_MESSAGE}
            </div>
            <UserTail bg={COLORS.primary} bgColor={COLORS.bgLight} />
          </div>
        </div>

        {/* GAIA response */}
        <div
          style={{
            display: "flex",
            alignItems: "flex-end",
            gap: 20,
            paddingLeft: 8,
            opacity: bubbleOpacity,
            transform: `translateY(${bubbleY}px)`,
          }}
        >
          <Img
            src={staticFile("images/logos/logo.webp")}
            style={{ width: 60, height: 60, borderRadius: "50%", objectFit: "contain", flexShrink: 0 }}
          />
          <div style={{ display: "flex", flexDirection: "column", gap: 24, flex: 1 }}>
            {/* Text bubble */}
            <div style={{ position: "relative" }}>
              <div
                style={{
                  background: "#27272a",
                  color: "white",
                  padding: "18px 32px",
                  borderRadius: "40px 40px 40px 8px",
                  fontSize: 28,
                  lineHeight: 1.65,
                  fontFamily: FONTS.body,
                  whiteSpace: "pre-wrap",
                  maxWidth: 1100,
                }}
              >
                <TypingText
                  text={BOT_MESSAGE}
                  framesPerChar={0.7}
                  delay={0}
                  cursorColor={COLORS.primary}
                  showCursor={!messageComplete}
                  style={{ display: "block", whiteSpace: "pre-wrap" }}
                />
              </div>
              <BotTail bgColor={COLORS.bgLight} />
            </div>

            {/* WorkflowDraftVideoCard */}
            {frame >= cardDelay && (
              <div style={{ transform: `translateY(${cardY}px) scale(${cardScale})`, opacity: cardOpacity, transformOrigin: "top left" }}>
                <WorkflowDraftVideoCard
                  title="Daily Morning Briefing"
                  description="Pulls Gmail, Calendar, GitHub, and Slack each morning and delivers a clean summary."
                  schedule="Every day at 8:00 AM"
                />
              </div>
            )}
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};
