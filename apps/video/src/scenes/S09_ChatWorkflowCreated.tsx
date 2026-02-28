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
import { CheckmarkCircle02Icon } from "@theexperiencecompany/gaia-icons/solid-rounded";
import { COLORS, FONTS } from "../constants";
import { UserTail, BotTail } from "./S06_UserChat";
import { WorkflowVideoCard } from "../components/WorkflowVideoCard";
import { WorkflowDraftVideoCard } from "../components/WorkflowDraftVideoCard";

const USER_MESSAGE =
  "Hey GAIA — pull my Gmail from the last 6 hours, check Google Calendar for today's meetings, scan my GitHub for open PRs, and check Slack for anything urgent. Summarize everything and set this up to run every morning at 8am automatically.";

const BOT_SUMMARY =
  "📬 14 emails, 2 need replies. 📅 3 meetings today. 🔧 2 overnight PRs. 💬 3 DMs in #design.\n\nI've drafted your daily briefing workflow below.";

const CONFIRM_MESSAGE = "Yes, create it";

export const S09_ChatWorkflowCreated: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const confirmProgress = spring({ frame, fps, config: { damping: 22, stiffness: 120 } });
  const confirmOpacity = interpolate(confirmProgress, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });
  const confirmY = interpolate(confirmProgress, [0, 1], [20, 0]);

  const swapFrame = 40;
  const showCreated = frame >= swapFrame;

  const createdProgress = spring({ frame: frame - swapFrame, fps, config: { damping: 12, stiffness: 180 } });
  const createdScale = showCreated ? interpolate(createdProgress, [0, 0.5, 1], [0.85, 1.06, 1.0]) : 0;
  const createdOpacity = showCreated ? interpolate(createdProgress, [0, 0.1], [0, 1], { extrapolateRight: "clamp" }) : 0;

  const flashOpacity = interpolate(frame, [swapFrame, swapFrame + 8, swapFrame + 55, swapFrame + 70], [0, 1, 1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill style={{ background: COLORS.bgLight, display: "flex", alignItems: "center", justifyContent: "center" }}>
      {/* "✓ Workflow created." flash */}
      {frame >= swapFrame && (
        <div
          style={{
            position: "absolute",
            top: 60,
            left: "50%",
            transform: "translateX(-50%)",
            display: "flex",
            alignItems: "center",
            gap: 16,
            fontSize: 56,
            fontFamily: FONTS.body,
            fontWeight: 700,
            color: COLORS.textDark,
            opacity: flashOpacity,
            zIndex: 10,
            whiteSpace: "nowrap",
          }}
        >
          <CheckmarkCircle02Icon size={52} style={{ color: "#22c55e" }} />
          Workflow created.
        </div>
      )}

      <div style={{ width: 1400, display: "flex", flexDirection: "column", gap: 28 }}>
        {/* Original user message (very faded) */}
        <div style={{ display: "flex", justifyContent: "flex-end", paddingRight: 32, opacity: 0.3 }}>
          <div style={{ position: "relative" }}>
            <div style={{ background: COLORS.primary, color: "#000", padding: "10px 22px", borderRadius: "40px 40px 8px 40px", fontSize: 22, lineHeight: 1.5, fontWeight: 500, fontFamily: FONTS.body, maxWidth: 900 }}>
              {USER_MESSAGE}
            </div>
            <UserTail bg={COLORS.primary} bgColor={COLORS.bgLight} />
          </div>
        </div>

        {/* GAIA summary + card */}
        <div style={{ display: "flex", alignItems: "flex-end", gap: 20, paddingLeft: 8 }}>
          <Img src={staticFile("images/logos/logo.webp")} style={{ width: 60, height: 60, borderRadius: "50%", objectFit: "contain", flexShrink: 0 }} />
          <div style={{ display: "flex", flexDirection: "column", gap: 20, flex: 1 }}>
            <div style={{ position: "relative" }}>
              <div style={{ background: "#27272a", color: "white", padding: "14px 28px", borderRadius: "40px 40px 40px 8px", fontSize: 26, lineHeight: 1.6, fontFamily: FONTS.body, whiteSpace: "pre-wrap", maxWidth: 1000, opacity: 0.85 }}>
                {BOT_SUMMARY}
              </div>
              <BotTail bgColor={COLORS.bgLight} />
            </div>

            {/* Draft → Created swap */}
            {!showCreated && (
              <WorkflowDraftVideoCard
                title="Daily Morning Briefing"
                description="Pulls Gmail, Calendar, GitHub, and Slack each morning and delivers a clean summary."
                schedule="Every day at 8:00 AM"
              />
            )}
            {showCreated && (
              <div style={{ transform: `scale(${createdScale})`, opacity: createdOpacity, transformOrigin: "top left" }}>
                <WorkflowVideoCard
                  title="Daily Morning Briefing"
                  description="Pulls Gmail, Calendar, GitHub, and Slack each morning and delivers a clean summary."
                  schedule="Every day at 8:00 AM"
                  status="done"
                />
              </div>
            )}
          </div>
        </div>

        {/* User confirmation bubble */}
        <div style={{ display: "flex", justifyContent: "flex-end", paddingRight: 32, opacity: confirmOpacity, transform: `translateY(${confirmY}px)` }}>
          <div style={{ position: "relative" }}>
            <div style={{ background: COLORS.primary, color: "#000", padding: "14px 32px", borderRadius: "40px 40px 8px 40px", fontSize: 32, fontWeight: 400, fontFamily: FONTS.body }}>
              {CONFIRM_MESSAGE}
            </div>
            <UserTail bg={COLORS.primary} bgColor={COLORS.bgLight} />
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};
