import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig, spring, interpolate } from "remotion";
import { COLORS, FONTS } from "../constants";
import { SceneBackground } from "../components/SceneBackground";
import { WorkflowVideoCard } from "../components/WorkflowVideoCard";

export const S21_Completed: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Workflow card entrance
  const cardProgress = spring({ frame, fps, config: { damping: 22 } });
  const cardScale = interpolate(cardProgress, [0, 0.5, 1], [0.92, 1.04, 1.0]);
  const cardOpacity = interpolate(cardProgress, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });

  // "Done." overlay
  const doneProgress = spring({ frame: frame - 10, fps, config: { damping: 200 } });
  const doneOpacity = interpolate(doneProgress, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });
  const doneFadeOut = interpolate(frame, [70, 90], [1, 0], {
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
            fontFamily: FONTS.display, textTransform: "uppercase" as const,
            fontSize: 200,
            fontWeight: 700,
            color: COLORS.textDark,
            opacity: doneOpacity * doneFadeOut,
          }}
        >
          Delivered.
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
        <div style={{ width: 900, transform: `scale(${cardScale})`, opacity: cardOpacity, transformOrigin: "center center" }}>
          <WorkflowVideoCard
            title="Daily Morning Briefing"
            description="Pulls Gmail, Calendar, GitHub, and Slack each morning and delivers a clean summary."
            schedule="Every day at 8:00 AM"
            status="completed"
          />
        </div>
      </div>
    </AbsoluteFill>
  );
};
