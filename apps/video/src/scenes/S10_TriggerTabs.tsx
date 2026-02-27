import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig, spring, interpolate } from "remotion";
import { COLORS, FONTS } from "../constants";
import { SceneBackground } from "../components/SceneBackground";

export const S10_TriggerTabs: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Camera shifts DOWN to trigger section
  const cameraProgress = spring({ frame, fps, config: { damping: 20, stiffness: 80 } });
  const cameraY = interpolate(cameraProgress, [0, 1], [0, 60]);

  // Label overlay: "Choose how it runs" — fades in then out
  const labelOpacity = interpolate(frame, [15, 25, 90, 110], [0, 1, 1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Tab indicator glow
  const glowProgress = spring({ frame: frame - 10, fps, config: { damping: 30 } });
  const glowOpacity = interpolate(glowProgress, [0, 1], [0, 1]);

  return (
    <AbsoluteFill>
      <SceneBackground variant="mesh" meshOpacity={0.15} />

      {/* "Choose how it runs" overlay label */}
      <div
        style={{
          position: "absolute",
          top: 80,
          left: "50%",
          transform: "translateX(-50%)",
          fontSize: 38,
          fontFamily: FONTS.body,
          fontWeight: 700,
          color: COLORS.zinc400,
          opacity: labelOpacity,
          zIndex: 10,
          whiteSpace: "nowrap",
        }}
      >
        Choose how it runs
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
              <span style={{ color: "white", fontSize: 18, fontWeight: 600, fontFamily: FONTS.body }}>Create Workflow</span>
            </div>

            <div style={{ flex: 1, display: "flex" }}>
              <div style={{ flex: 1, padding: 24, display: "flex", flexDirection: "column", gap: 20, borderRight: "1px solid #27272a" }}>
                <div>
                  <div style={{ fontSize: 13, color: "#a1a1aa", marginBottom: 8, fontFamily: FONTS.body }}>Workflow Name</div>
                  <div style={{ background: "#27272a", border: "1px solid #3f3f46", borderRadius: 8, padding: "10px 14px", color: "white", fontSize: 15, fontFamily: FONTS.body }}>
                    Daily Email Digest &amp; Briefing
                  </div>
                </div>

                <div>
                  <div style={{ fontSize: 13, color: "#a1a1aa", marginBottom: 8, fontFamily: FONTS.body }}>Description</div>
                  <div style={{ background: "#27272a", border: "1px solid #3f3f46", borderRadius: 8, padding: "10px 14px", color: "white", fontSize: 14, fontFamily: FONTS.body }}>
                    Summarize emails, post briefing to Slack
                  </div>
                </div>

                {/* Trigger section — focused */}
                <div>
                  <div style={{ fontSize: 13, color: "#a1a1aa", marginBottom: 8, fontFamily: FONTS.body }}>Trigger</div>
                  <div style={{ display: "flex", gap: 8 }}>
                    {["Manual", "Schedule", "Event"].map((tab, i) => (
                      <div
                        key={i}
                        style={{
                          padding: "8px 18px",
                          borderRadius: 8,
                          background: i === 0 ? "#3f3f46" : "transparent",
                          border: i === 0 ? `1px solid ${COLORS.primary}` : "1px solid #3f3f46",
                          color: i === 0 ? "white" : "#71717a",
                          fontSize: 14,
                          fontFamily: FONTS.body,
                          fontWeight: i === 0 ? 600 : 400,
                          boxShadow: i === 0 ? `inset 0 -2px 0 ${COLORS.primary}` : "none",
                          opacity: glowOpacity,
                        }}
                      >
                        {tab}
                      </div>
                    ))}
                  </div>

                  <div style={{ marginTop: 12, padding: 16, background: "#0d0d0d", borderRadius: 8, border: "1px solid #27272a" }}>
                    <div style={{ color: "#71717a", fontSize: 13, fontFamily: FONTS.body }}>
                      Run this workflow on demand from GAIA chat or API.
                    </div>
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
