import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig, spring, interpolate } from "remotion";
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

  const showRunning = frame >= 20;

  // Running pulse ring
  const pulseProg = spring({ frame: frame - 20, fps, config: { damping: 30 } });
  const pulseSize = interpolate(pulseProg, [0, 1], [0, 10]);

  return (
    <AbsoluteFill>
      <SceneBackground variant="light" />

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
        <span style={{ color: "#22c55e" }}>✓</span>
        Workflow created.
      </div>

      {/* Content directly on white bg, centered, 1400px wide */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <div style={{ width: 960, display: "flex", flexDirection: "column", gap: 28 }}>
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
              status={showRunning ? "running" : "ready"}
            />
          </div>

          {/* Running pulse indicator */}
          {showRunning && (
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <div
                style={{
                  width: 12,
                  height: 12,
                  borderRadius: "50%",
                  background: COLORS.primary,
                  boxShadow: `0 0 0 ${pulseSize}px ${COLORS.primary}22`,
                }}
              />
              <span style={{ color: COLORS.zinc600, fontSize: 20, fontFamily: FONTS.body }}>
                Running workflow...
              </span>
            </div>
          )}
        </div>
      </div>
    </AbsoluteFill>
  );
};
