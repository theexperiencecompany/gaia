import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig, spring, interpolate } from "remotion";
import { COLORS, FONTS } from "../constants";
import { SceneBackground } from "../components/SceneBackground";
import { TypingText } from "../components/TypingText";

export const S12_CronSchedule: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Schedule card fades in
  const cardProgress = spring({ frame, fps, config: { damping: 25 } });
  const cardOpacity = interpolate(cardProgress, [0, 0.2], [0, 1], { extrapolateRight: "clamp" });
  const cardY = interpolate(cardProgress, [0, 1], [10, 0]);

  // Checkmark appears after time types
  const checkFrame = 50;
  const checkProgress = spring({
    frame: frame - checkFrame,
    fps,
    config: { damping: 12 },
  });
  const checkScale = interpolate(checkProgress, [0, 0.5, 1], [0, 1.2, 1.0]);
  const checkOpacity = interpolate(checkProgress, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });

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
            transform: "scale(1.4) translateY(60px)",
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

                {/* Trigger — Schedule selected */}
                <div>
                  <div style={{ fontSize: 13, color: "#a1a1aa", marginBottom: 8, fontFamily: FONTS.body }}>Trigger</div>
                  <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
                    {["Manual", "Schedule", "Event"].map((tab, i) => (
                      <div
                        key={i}
                        style={{
                          padding: "8px 18px",
                          borderRadius: 8,
                          background: i === 1 ? "#3f3f46" : "transparent",
                          border: `1px solid ${i === 1 ? COLORS.primary : "#3f3f46"}`,
                          color: i === 1 ? "white" : "#71717a",
                          fontSize: 14,
                          fontFamily: FONTS.body,
                          fontWeight: i === 1 ? 600 : 400,
                          boxShadow: i === 1 ? `inset 0 -2px 0 ${COLORS.primary}` : "none",
                        }}
                      >
                        {tab}
                      </div>
                    ))}
                  </div>

                  {/* Schedule card */}
                  <div
                    style={{
                      background: "#27272a",
                      border: "1px solid #3f3f46",
                      borderRadius: 12,
                      padding: "16px 20px",
                      opacity: cardOpacity,
                      transform: `translateY(${cardY}px)`,
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 8 }}>
                      <span style={{ fontSize: 20 }}>🕗</span>
                      <div>
                        <div style={{ fontFamily: FONTS.body, fontWeight: 700, fontSize: 24, color: COLORS.primary }}>
                          <TypingText text="8:00 AM" framesPerChar={5} delay={5} />
                        </div>
                        <div style={{ fontFamily: FONTS.body, fontSize: 14, color: COLORS.zinc400 }}>
                          Every day
                        </div>
                      </div>
                      {/* Checkmark */}
                      <div
                        style={{
                          marginLeft: "auto",
                          width: 28,
                          height: 28,
                          borderRadius: "50%",
                          background: "#22c55e22",
                          border: "1px solid #22c55e66",
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                          fontSize: 14,
                          transform: `scale(${checkScale})`,
                          opacity: checkOpacity,
                        }}
                      >
                        ✓
                      </div>
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
