import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig, spring, interpolate } from "remotion";
import { COLORS, FONTS } from "../constants";
import { SceneBackground } from "../components/SceneBackground";

const STEPS = [
  { icon: "📥", label: "Fetch latest emails from Gmail", color: "#EA4335" },
  { icon: "🧠", label: "Summarize key highlights with AI", color: "#00bbff" },
  { icon: "📝", label: "Create summary doc in Google Docs", color: "#4285F4" },
  { icon: "📣", label: "Post briefing to Slack #daily", color: "#E01E5A" },
];

interface StepCardProps {
  step: (typeof STEPS)[number];
  index: number;
}

const StepCard: React.FC<StepCardProps> = ({ step, index }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const delay = index * 18;
  const progress = spring({
    frame: frame - delay,
    fps,
    config: { damping: 20, stiffness: 120 },
  });

  const scale = interpolate(progress, [0, 1], [0.9, 1.0]);
  const opacity = interpolate(progress, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });
  const y = interpolate(progress, [0, 1], [20, 0]);

  // Dot pulse
  const dotPulseDelay = delay + 10;
  const dotPulse = spring({
    frame: frame - dotPulseDelay,
    fps,
    config: { damping: 12 },
    durationInFrames: 20,
  });
  const dotScale = frame > dotPulseDelay ? interpolate(dotPulse, [0, 0.5, 1], [1, 1.3, 1.0]) : 1;

  return (
    <div
      style={{
        height: 56,
        background: "#27272a",
        borderRadius: 8,
        border: "1px solid #3f3f46",
        padding: "0 14px",
        display: "flex",
        alignItems: "center",
        gap: 12,
        transform: `scale(${scale}) translateY(${y}px)`,
        opacity,
      }}
    >
      <div
        style={{
          width: 28,
          height: 28,
          borderRadius: "50%",
          background: step.color + "22",
          border: `1px solid ${step.color}66`,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: 14,
          transform: `scale(${dotScale})`,
        }}
      >
        {step.icon}
      </div>
      <span style={{ color: "white", fontSize: 14, fontFamily: FONTS.body, flex: 1 }}>
        {step.label}
      </span>
    </div>
  );
};

export const S14_StepsPopin: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // "Your workflow, built instantly." label
  const labelDelay = 60;
  const labelProgress = spring({ frame: frame - labelDelay, fps, config: { damping: 200 } });
  const labelOpacity = interpolate(labelProgress, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });

  return (
    <AbsoluteFill>
      <SceneBackground variant="mesh" meshOpacity={0.15} />

      {/* Label overlay */}
      {frame >= labelDelay && (
        <div
          style={{
            position: "absolute",
            top: 80,
            left: "50%",
            transform: "translateX(-50%)",
            fontSize: 36,
            fontFamily: FONTS.body,
            fontWeight: 700,
            color: COLORS.white,
            opacity: labelOpacity,
            zIndex: 10,
            whiteSpace: "nowrap",
          }}
        >
          Your workflow, built instantly.
        </div>
      )}

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
            transform: "scale(1.4) translateX(-80px)",
            transformOrigin: "center center",
          }}
        >
          <div
            style={{
              width: 900,
              height: 620,
              background: "#18181b",
              border: "1px solid #27272a",
              borderRadius: 16,
              display: "flex",
              flexDirection: "column",
              overflow: "hidden",
            }}
          >
            <div style={{ padding: "20px 24px", borderBottom: "1px solid #27272a" }}>
              <span style={{ color: "white", fontSize: 18, fontWeight: 600, fontFamily: FONTS.body }}>Create Workflow</span>
            </div>

            <div style={{ flex: 1, display: "flex" }}>
              <div style={{ flex: 1, padding: 24, borderRight: "1px solid #27272a" }}>
                <div style={{ color: "white", fontSize: 15, fontFamily: FONTS.body, marginBottom: 8 }}>
                  Daily Email Digest &amp; Briefing
                </div>
                <div style={{ color: COLORS.zinc400, fontSize: 14, fontFamily: FONTS.body }}>
                  Schedule • Every day at 8:00 AM
                </div>
              </div>

              {/* Right panel — steps popping in */}
              <div style={{ width: 320, padding: 24, display: "flex", flexDirection: "column", gap: 10 }}>
                <div style={{ fontSize: 13, color: "#a1a1aa", marginBottom: 4, fontFamily: FONTS.body }}>Steps</div>
                {STEPS.map((step, i) => (
                  <StepCard key={i} step={step} index={i} />
                ))}
              </div>
            </div>

            <div style={{ padding: "16px 24px", borderTop: "1px solid #27272a", display: "flex", justifyContent: "flex-end" }}>
              <div style={{ padding: "10px 24px", borderRadius: 8, background: COLORS.primary, color: "#000", fontSize: 14, fontWeight: 700, fontFamily: FONTS.body }}>
                Create Workflow
              </div>
            </div>
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};
