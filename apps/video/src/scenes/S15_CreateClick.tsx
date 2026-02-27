import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig, spring, interpolate } from "remotion";
import { COLORS, FONTS } from "../constants";
import { SceneBackground } from "../components/SceneBackground";
import { CursorDot } from "../components/CursorDot";

export const S15_CreateClick: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Camera shifts DOWN to footer
  const cameraProgress = spring({ frame, fps, config: { damping: 20, stiffness: 80 } });
  const cameraY = interpolate(cameraProgress, [0, 1], [0, 120]);

  // Click at frame 18
  const clickFrame = 18;
  const btnProgress = spring({
    frame: frame - clickFrame,
    fps,
    config: { damping: 30, stiffness: 400 },
    durationInFrames: 15,
  });
  const btnScale = frame >= clickFrame
    ? interpolate(btnProgress, [0, 0.5, 1], [1, 0.94, 1.0])
    : 1;

  // Button glow before click
  const glowPulse = interpolate(
    Math.sin((frame / 15) * Math.PI),
    [-1, 1],
    [0.0, 1.0],
  );
  const btnGlow = frame < clickFrame ? `0 0 ${glowPulse * 20}px ${COLORS.primary}55` : "none";

  // Ripple
  const rippleProgress = spring({
    frame: frame - clickFrame,
    fps,
    config: { damping: 200 },
    durationInFrames: 20,
  });

  const cursorPositions = [
    { x: 0, y: 0, frame: 0 },
    { x: 310, y: 0, frame: 12 }, // move to Create Workflow button
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
            transform: `scale(1.4) translate(-80px, ${cameraY}px)`,
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
              overflow: "visible",
            }}
          >
            <div style={{ padding: "20px 24px", borderBottom: "1px solid #27272a" }}>
              <span style={{ color: "white", fontSize: 18, fontWeight: 600, fontFamily: FONTS.body }}>Create Workflow</span>
            </div>

            <div style={{ flex: 1, display: "flex" }}>
              <div style={{ flex: 1, padding: 24, borderRight: "1px solid #27272a" }}>
                <div style={{ color: "white", fontSize: 15, fontFamily: FONTS.body, marginBottom: 8 }}>Daily Email Digest &amp; Briefing</div>
                <div style={{ color: COLORS.zinc400, fontSize: 14, fontFamily: FONTS.body }}>Schedule • Every day at 8:00 AM</div>
              </div>
              <div style={{ width: 320, padding: 24 }}>
                <div style={{ fontSize: 13, color: "#a1a1aa", fontFamily: FONTS.body }}>4 steps ready</div>
              </div>
            </div>

            {/* Footer — focused */}
            <div
              style={{
                padding: "16px 24px",
                borderTop: `1px solid ${COLORS.primary}44`,
                display: "flex",
                justifyContent: "flex-end",
                gap: 12,
                background: "#1a1a1d",
                position: "relative",
              }}
            >
              <div style={{ padding: "10px 20px", borderRadius: 8, border: "1px solid #3f3f46", color: "#a1a1aa", fontSize: 14, fontFamily: FONTS.body }}>
                Cancel
              </div>

              <div
                style={{
                  padding: "10px 24px",
                  borderRadius: 12,
                  background: COLORS.primary,
                  color: "#000000",
                  fontSize: 18,
                  fontWeight: 700,
                  fontFamily: FONTS.body,
                  boxShadow: btnGlow,
                  transform: `scale(${btnScale})`,
                  position: "relative",
                  overflow: "visible",
                }}
              >
                Create Workflow
                {/* Click ripple */}
                {frame >= clickFrame && (
                  <div
                    style={{
                      position: "absolute",
                      inset: 0,
                      borderRadius: 12,
                      width: "100%",
                      height: "100%",
                      background: "rgba(0, 187, 255, 0.4)",
                      transform: `scale(${1 + rippleProgress * 1.5})`,
                      opacity: Math.max(0, 1 - rippleProgress),
                      pointerEvents: "none",
                    }}
                  />
                )}
              </div>
            </div>
          </div>

          <CursorDot positions={cursorPositions} clickFrame={clickFrame} />
        </div>
      </div>
    </AbsoluteFill>
  );
};
