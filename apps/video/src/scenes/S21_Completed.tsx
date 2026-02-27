import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig, spring, interpolate, Img, staticFile } from "remotion";
import { COLORS, FONTS } from "../constants";
import { SceneBackground } from "../components/SceneBackground";
import { BotTail } from "./S06_UserChat";
import { WorkflowVideoCard } from "../components/WorkflowVideoCard";

export const S21_Completed: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Workflow card entrance
  const cardProgress = spring({ frame, fps, config: { damping: 22 } });
  const cardScale = interpolate(cardProgress, [0, 0.5, 1], [0.92, 1.04, 1.0]);
  const cardOpacity = interpolate(cardProgress, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });

  // Success message entrance after card
  const msgProgress = spring({ frame: frame - 15, fps, config: { damping: 25 } });
  const msgOpacity = interpolate(msgProgress, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });
  const msgY = interpolate(msgProgress, [0, 1], [20, 0]);

  // "Done." overlay
  const doneProgress = spring({ frame: frame - 10, fps, config: { damping: 200 } });
  const doneOpacity = interpolate(doneProgress, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });
  const doneFadeOut = interpolate(frame, [48, 66], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill>
      <SceneBackground variant="light" />

      {/* "Done." overlay — massive, center screen, fades out */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          pointerEvents: "none",
          zIndex: 5,
        }}
      >
        <div
          style={{
            fontFamily: FONTS.display,
            fontSize: 200,
            fontWeight: 700,
            color: COLORS.textDark,
            opacity: doneOpacity * doneFadeOut,
          }}
        >
          Done.
        </div>
      </div>

      <div
        style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          opacity: 1 - doneOpacity * doneFadeOut * 0.8,
        }}
      >
        <div style={{ width: 1400, display: "flex", flexDirection: "column", gap: 32 }}>
          {/* WorkflowVideoCard — done status */}
          <div style={{ transform: `scale(${cardScale})`, opacity: cardOpacity, transformOrigin: "top center" }}>
            <WorkflowVideoCard
              title="Daily Morning Briefing"
              description="Pulls Gmail, Calendar, GitHub, and Slack each morning and delivers a clean summary."
              schedule="Every day at 8:00 AM"
              status="done"
            />
          </div>

          {/* GAIA success message */}
          <div
            style={{
              display: "flex",
              alignItems: "flex-end",
              gap: 20,
              paddingLeft: 8,
              opacity: msgOpacity,
              transform: `translateY(${msgY}px)`,
            }}
          >
            <Img
              src={staticFile("images/logos/logo.webp")}
              style={{ width: 60, height: 60, borderRadius: "50%", objectFit: "contain", flexShrink: 0 }}
            />
            <div style={{ position: "relative" }}>
              <div
                style={{
                  background: "#27272a",
                  color: "white",
                  padding: "18px 32px",
                  borderRadius: "40px 40px 40px 8px",
                  fontSize: 30,
                  lineHeight: 1.5,
                  fontFamily: FONTS.body,
                }}
              >
                Daily briefing sent. 4 tools used in 3.2s.
              </div>
              <BotTail bgColor={COLORS.bgLight} />
            </div>
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};
