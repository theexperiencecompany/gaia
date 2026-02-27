import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig, spring, interpolate } from "remotion";
import { COLORS, FONTS } from "../constants";
import { SceneBackground } from "../components/SceneBackground";

const AI_LINES = [
  "Fetch all emails received in the last 24 hours",
  "Summarize key highlights and action items",
  "Format as a Slack-friendly digest with sections",
  "Post to #daily-briefing channel at 8 AM",
  "Save summary to Google Docs for archival",
];

interface StreamLineProps {
  text: string;
  lineDelay: number;
}

const StreamLine: React.FC<StreamLineProps> = ({ text, lineDelay }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const progress = spring({
    frame: frame - lineDelay,
    fps,
    config: { damping: 30, stiffness: 150 },
  });

  const y = interpolate(progress, [0, 1], [15, 0]);
  const opacity = interpolate(progress, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });

  // Shimmer
  const shimmerX = interpolate((frame - lineDelay) % 60, [0, 60], [-100, 200], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <div
      style={{
        transform: `translateY(${y}px)`,
        opacity,
        fontSize: 14,
        fontFamily: FONTS.body,
        color: "white",
        padding: "6px 10px",
        borderRadius: 6,
        background: "#27272a",
        border: "1px solid #3f3f46",
        display: "flex",
        alignItems: "center",
        gap: 8,
        overflow: "hidden",
        position: "relative",
      }}
    >
      <span style={{ color: COLORS.primary, fontSize: 12 }}>•</span>
      {text}
      {/* Shimmer overlay */}
      {frame - lineDelay < 30 && (
        <div
          style={{
            position: "absolute",
            top: 0,
            left: shimmerX,
            width: 80,
            height: "100%",
            background:
              "linear-gradient(90deg, transparent 0%, rgba(255,255,255,0.08) 50%, transparent 100%)",
            pointerEvents: "none",
          }}
        />
      )}
    </div>
  );
};

export const S09_AIInstructions: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Camera stays centered
  const cameraProgress = spring({ frame, fps, config: { damping: 20, stiffness: 80 } });
  const cameraY = interpolate(cameraProgress, [0, 1], [0, 10]);

  return (
    <AbsoluteFill>
      <SceneBackground variant="mesh" meshOpacity={0.15} />
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
            transform: `scale(1.4) translateY(${cameraY}px)`,
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
              <span style={{ color: "white", fontSize: 18, fontWeight: 600, fontFamily: FONTS.body }}>
                Create Workflow
              </span>
            </div>

            <div style={{ flex: 1, display: "flex" }}>
              <div style={{ flex: 1, padding: 24, display: "flex", flexDirection: "column", gap: 20, borderRight: "1px solid #27272a" }}>
                <div>
                  <div style={{ fontSize: 13, color: "#a1a1aa", marginBottom: 8, fontFamily: FONTS.body }}>Workflow Name</div>
                  <div style={{ background: "#27272a", border: "1px solid #3f3f46", borderRadius: 8, padding: "10px 14px", color: "white", fontSize: 15, fontFamily: FONTS.body }}>
                    Daily Email Digest &amp; Briefing
                  </div>
                </div>

                {/* AI Instructions streaming area */}
                <div>
                  <div style={{ fontSize: 13, color: "#a1a1aa", marginBottom: 8, fontFamily: FONTS.body, display: "flex", alignItems: "center", gap: 8 }}>
                    AI Instructions
                    <span style={{ color: COLORS.primary, fontSize: 11 }}>● generating...</span>
                  </div>
                  <div
                    style={{
                      background: "#1a1a1d",
                      border: `1px solid ${COLORS.primary}33`,
                      borderRadius: 8,
                      padding: 12,
                      display: "flex",
                      flexDirection: "column",
                      gap: 6,
                      minHeight: 160,
                    }}
                  >
                    {AI_LINES.map((line, i) => (
                      <StreamLine key={i} text={line} lineDelay={i * 25} />
                    ))}
                  </div>
                </div>
              </div>

              <div style={{ width: 320, padding: 24, display: "flex", flexDirection: "column", gap: 12 }}>
                <div style={{ fontSize: 13, color: "#a1a1aa", marginBottom: 4, fontFamily: FONTS.body }}>Steps</div>
                {[0, 1, 2, 3].map((i) => (
                  <div key={i} style={{ height: 56, background: "#27272a", borderRadius: 8, border: "1px solid #3f3f46", padding: "0 14px", display: "flex", alignItems: "center", gap: 10 }}>
                    <div style={{ width: 28, height: 28, borderRadius: "50%", background: "#3f3f46" }} />
                    <div style={{ flex: 1, height: 10, background: "#3f3f46", borderRadius: 5 }} />
                  </div>
                ))}
              </div>
            </div>

            <div style={{ padding: "16px 24px", borderTop: "1px solid #27272a", display: "flex", justifyContent: "flex-end", gap: 12 }}>
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
