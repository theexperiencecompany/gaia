import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig, spring, interpolate } from "remotion";
import { COLORS, FONTS } from "../constants";
import { SceneBackground } from "../components/SceneBackground";
import { TypingText } from "../components/TypingText";

const TITLE_TEXT = "Daily Email Digest & Briefing";

export const S07_TypingTitle: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Camera shift up to focus on title
  const cameraProgress = spring({ frame, fps, config: { damping: 20, stiffness: 80 } });
  const cameraY = interpolate(cameraProgress, [0, 1], [0, -40]);

  // Camera breathe during typing
  const charIndex = Math.min(Math.floor(frame / 3), TITLE_TEXT.length);
  const cameraX = interpolate(charIndex / TITLE_TEXT.length, [0, 1], [0, -20]);

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
            transform: `scale(1.4) translate(${cameraX}px, ${cameraY}px)`,
            transformOrigin: "center center",
          }}
        >
          {/* Modal frame */}
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
            {/* Header */}
            <div
              style={{
                padding: "20px 24px",
                borderBottom: "1px solid #27272a",
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
              }}
            >
              <span style={{ color: "white", fontSize: 18, fontWeight: 600, fontFamily: FONTS.body }}>
                Create Workflow
              </span>
            </div>

            {/* Body */}
            <div style={{ flex: 1, display: "flex" }}>
              <div style={{ flex: 1, padding: 24, display: "flex", flexDirection: "column", gap: 20, borderRight: "1px solid #27272a" }}>
                {/* Title field — highlighted */}
                <div>
                  <div style={{ fontSize: 13, color: "#a1a1aa", marginBottom: 8, fontFamily: FONTS.body }}>
                    Workflow Name
                  </div>
                  <div
                    style={{
                      background: "#27272a",
                      border: `1px solid ${COLORS.primary}66`,
                      borderRadius: 8,
                      padding: "10px 14px",
                      color: "white",
                      fontSize: 15,
                      fontFamily: FONTS.body,
                      boxShadow: `0 0 0 2px ${COLORS.primary}22`,
                      minHeight: 44,
                    }}
                  >
                    <TypingText text={TITLE_TEXT} framesPerChar={3} delay={0} />
                  </div>
                </div>

                {/* Description (empty) */}
                <div>
                  <div style={{ fontSize: 13, color: "#a1a1aa", marginBottom: 8, fontFamily: FONTS.body }}>
                    Description
                  </div>
                  <div
                    style={{
                      background: "#27272a",
                      border: "1px solid #3f3f46",
                      borderRadius: 8,
                      padding: "10px 14px",
                      color: "#71717a",
                      fontSize: 15,
                      height: 100,
                      fontFamily: FONTS.body,
                    }}
                  >
                    Describe what this workflow does...
                  </div>
                </div>

                {/* Triggers */}
                <div>
                  <div style={{ fontSize: 13, color: "#a1a1aa", marginBottom: 8, fontFamily: FONTS.body }}>Trigger</div>
                  <div style={{ display: "flex", gap: 8 }}>
                    {["Manual", "Schedule", "Event"].map((tab, i) => (
                      <div
                        key={i}
                        style={{
                          padding: "6px 14px",
                          borderRadius: 6,
                          background: i === 0 ? "#3f3f46" : "transparent",
                          border: "1px solid #3f3f46",
                          color: i === 0 ? "white" : "#71717a",
                          fontSize: 13,
                          fontFamily: FONTS.body,
                        }}
                      >
                        {tab}
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              {/* Right panel steps */}
              <div style={{ width: 320, padding: 24, display: "flex", flexDirection: "column", gap: 12 }}>
                <div style={{ fontSize: 13, color: "#a1a1aa", marginBottom: 4, fontFamily: FONTS.body }}>Steps</div>
                {[0, 1, 2, 3].map((i) => (
                  <div
                    key={i}
                    style={{
                      height: 56,
                      background: "#27272a",
                      borderRadius: 8,
                      border: "1px solid #3f3f46",
                      padding: "0 14px",
                      display: "flex",
                      alignItems: "center",
                      gap: 10,
                    }}
                  >
                    <div style={{ width: 28, height: 28, borderRadius: "50%", background: "#3f3f46" }} />
                    <div style={{ flex: 1, height: 10, background: "#3f3f46", borderRadius: 5 }} />
                  </div>
                ))}
              </div>
            </div>

            {/* Footer */}
            <div style={{ padding: "16px 24px", borderTop: "1px solid #27272a", display: "flex", justifyContent: "flex-end", gap: 12 }}>
              <div style={{ padding: "10px 20px", borderRadius: 8, border: "1px solid #3f3f46", color: "#a1a1aa", fontSize: 14, fontFamily: FONTS.body }}>
                Cancel
              </div>
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
