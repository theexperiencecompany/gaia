import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig, spring, interpolate } from "remotion";
import { COLORS, FONTS } from "../constants";
import { SceneBackground } from "../components/SceneBackground";
import { CursorDot } from "../components/CursorDot";

export const S11_SelectSchedule: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Cursor moves to Schedule tab and clicks
  const clickFrame = 30;
  const tabProgress = spring({
    frame: frame - clickFrame,
    fps,
    config: { damping: 30, stiffness: 400 },
    durationInFrames: 15,
  });

  // Active tab transitions at click
  const activeTab = frame >= clickFrame ? 1 : 0; // 0=Manual, 1=Schedule

  // Tab indicator slides
  const indicatorX = frame >= clickFrame
    ? interpolate(tabProgress, [0, 1], [0, 1])
    : 0;

  const cursorPositions = [
    { x: 0, y: 80, frame: 0 },     // start center
    { x: 80, y: 80, frame: 25 },    // move to Schedule tab
  ];

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
            position: "relative",
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

                {/* Trigger tabs */}
                <div>
                  <div style={{ fontSize: 13, color: "#a1a1aa", marginBottom: 8, fontFamily: FONTS.body }}>Trigger</div>
                  <div style={{ display: "flex", gap: 8 }}>
                    {["Manual", "Schedule", "Event"].map((tab, i) => {
                      const isActive = i === activeTab;
                      return (
                        <div
                          key={i}
                          style={{
                            padding: "8px 18px",
                            borderRadius: 8,
                            background: isActive ? "#3f3f46" : "transparent",
                            border: `1px solid ${isActive ? COLORS.primary : "#3f3f46"}`,
                            color: isActive ? "white" : "#71717a",
                            fontSize: 14,
                            fontFamily: FONTS.body,
                            fontWeight: isActive ? 600 : 400,
                            boxShadow: isActive ? `inset 0 -2px 0 ${COLORS.primary}` : "none",
                          }}
                        >
                          {tab}
                        </div>
                      );
                    })}
                  </div>

                  <div style={{ marginTop: 12, padding: 16, background: "#0d0d0d", borderRadius: 8, border: "1px solid #27272a" }}>
                    <div style={{ color: activeTab === 1 ? COLORS.zinc400 : "#71717a", fontSize: 13, fontFamily: FONTS.body }}>
                      {activeTab === 1
                        ? "Schedule this workflow to run automatically at set times."
                        : "Run this workflow on demand from GAIA chat or API."}
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

          <CursorDot positions={cursorPositions} clickFrame={clickFrame} />
        </div>
      </div>
    </AbsoluteFill>
  );
};
