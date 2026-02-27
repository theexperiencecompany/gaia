import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig, spring, interpolate } from "remotion";
import { COLORS, FONTS } from "../constants";
import { SceneBackground } from "../components/SceneBackground";

const SkeletonRow: React.FC<{ index: number }> = ({ index }) => {
  const frame = useCurrentFrame();

  // Shimmer animation
  const shimmerX = interpolate(
    ((frame + index * 15) % 60),
    [0, 60],
    [-100, 200],
  );

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
        gap: 10,
        overflow: "hidden",
        position: "relative",
      }}
    >
      <div style={{ width: 28, height: 28, borderRadius: "50%", background: "#3f3f46" }} />
      <div style={{ flex: 1, height: 10, background: "#3f3f46", borderRadius: 5 }} />
      {/* Shimmer overlay */}
      <div
        style={{
          position: "absolute",
          top: 0,
          left: shimmerX,
          width: 120,
          height: "100%",
          background:
            "linear-gradient(90deg, transparent 0%, rgba(255,255,255,0.06) 50%, transparent 100%)",
          pointerEvents: "none",
        }}
      />
    </div>
  );
};

export const S13_StepsGenerating: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Camera shifts LEFT to right panel
  const cameraProgress = spring({ frame, fps, config: { damping: 20, stiffness: 80 } });
  const cameraX = interpolate(cameraProgress, [0, 1], [0, -80]);

  // "GAIA is thinking..." label
  const labelOpacity = interpolate(frame, [5, 15, 90, 110], [0, 1, 1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Wave spinner dots
  const dots = [0, 1, 2];

  return (
    <AbsoluteFill>
      <SceneBackground variant="mesh" meshOpacity={0.15} />

      {/* "GAIA is thinking..." overlay */}
      <div
        style={{
          position: "absolute",
          top: 80,
          left: "50%",
          transform: "translateX(-50%)",
          fontSize: 32,
          fontFamily: FONTS.body,
          fontWeight: 500,
          color: COLORS.zinc400,
          opacity: labelOpacity,
          zIndex: 10,
          display: "flex",
          alignItems: "center",
          gap: 12,
          whiteSpace: "nowrap",
        }}
      >
        GAIA is thinking...
        <div style={{ display: "flex", gap: 4 }}>
          {dots.map((i) => (
            <div
              key={i}
              style={{
                width: 6,
                height: 6,
                borderRadius: "50%",
                background: COLORS.primary,
                opacity: interpolate(
                  Math.sin(((frame / 15) * Math.PI * 2 + i * 2) % (Math.PI * 2)),
                  [-1, 1],
                  [0.3, 1],
                ),
                transform: `translateY(${interpolate(
                  Math.sin(((frame / 15) * Math.PI * 2 + i * 2) % (Math.PI * 2)),
                  [-1, 1],
                  [2, -2],
                )}px)`,
              }}
            />
          ))}
        </div>
      </div>

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
            transform: `scale(1.4) translate(${cameraX}px, 0px)`,
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
              {/* Left panel */}
              <div style={{ flex: 1, padding: 24, borderRight: "1px solid #27272a" }}>
                <div style={{ color: "white", fontSize: 15, fontFamily: FONTS.body, marginBottom: 8 }}>
                  Daily Email Digest &amp; Briefing
                </div>
                <div style={{ color: COLORS.zinc400, fontSize: 14, fontFamily: FONTS.body }}>
                  Summarize emails, post briefing to Slack
                </div>
              </div>

              {/* Right panel — skeleton loading */}
              <div style={{ width: 320, padding: 24, display: "flex", flexDirection: "column", gap: 12 }}>
                <div style={{ fontSize: 13, color: "#a1a1aa", marginBottom: 4, fontFamily: FONTS.body, display: "flex", alignItems: "center", gap: 8 }}>
                  Steps
                  <div style={{ display: "flex", gap: 3 }}>
                    {dots.map((i) => (
                      <div
                        key={i}
                        style={{
                          width: 4,
                          height: 4,
                          borderRadius: "50%",
                          background: COLORS.primary,
                          opacity: interpolate(
                            Math.sin(((frame / 15) * Math.PI * 2 + i * 2) % (Math.PI * 2)),
                            [-1, 1],
                            [0.3, 1],
                          ),
                        }}
                      />
                    ))}
                  </div>
                </div>
                {[0, 1, 2, 3].map((i) => (
                  <SkeletonRow key={i} index={i} />
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
