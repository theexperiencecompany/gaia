import React from "react";
import { AbsoluteFill, Audio, Sequence, useCurrentFrame, useVideoConfig, spring, interpolate } from "remotion";
import { SFX } from "../sfx";
import { CheckmarkCircle02Icon } from "@theexperiencecompany/gaia-icons/solid-rounded";
import { COLORS, FONTS } from "../constants";
import { SceneBackground } from "../components/SceneBackground";
import { WorkflowVideoCard } from "../components/WorkflowVideoCard";

export const S16_ModalToCard: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Card slides in from below
  const cardProgress = spring({ frame, fps, config: { damping: 22, stiffness: 100 } });
  const cardY = interpolate(cardProgress, [0, 1], [40, 0]);
  const cardOpacity = interpolate(cardProgress, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });
  const cardScale = interpolate(cardProgress, [0, 1], [0.92, 1.0]);

  // "Workflow created." overlay
  const labelOpacity = interpolate(frame, [5, 15, 55, 70], [0, 1, 1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill>
      <SceneBackground variant="light" />
      {/* Swoosh as the card slides into view */}
      <Sequence from={0}>
        <Audio src={SFX.whoosh} volume={0.35} />
      </Sequence>

      {/* "✓ Workflow created." */}
      <div
        style={{
          position: "absolute",
          top: 80,
          left: "50%",
          transform: "translateX(-50%)",
          display: "flex",
          alignItems: "center",
          gap: 16,
          fontSize: 56,
          fontFamily: FONTS.body,
          fontWeight: 700,
          color: COLORS.textDark,
          opacity: labelOpacity,
          zIndex: 10,
          whiteSpace: "nowrap",
        }}
      >
        <CheckmarkCircle02Icon size={52} style={{ color: "#22c55e" }} />
        Workflow created.
      </div>

      {/* Content directly on white bg, centered */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <div
          style={{
            width: 700,
            display: "flex",
            flexDirection: "column",
            gap: 28,
            transform: "scale(1.2)",
            transformOrigin: "center center",
          }}
        >
          {/* WorkflowVideoCard with animation */}
          <div
            style={{
              transform: `translateY(${cardY}px) scale(${cardScale})`,
              opacity: cardOpacity,
              transformOrigin: "top center",
            }}
          >
            <WorkflowVideoCard
              title="Daily Morning Briefing"
              description="Pulls Gmail, Calendar, GitHub, and Slack each morning and delivers a clean summary."
              schedule="Every day at 8:00 AM"
              status="done"
            />
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};
