import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig, spring, interpolate } from "remotion";
import { COLORS, FONTS } from "../constants";
import { SceneBackground } from "../components/SceneBackground";
import { TypingText } from "../components/TypingText";
import { CursorDot } from "../components/CursorDot";

const DESC_TEXT = "Summarize emails, post briefing to Slack";
const TYPING_END = DESC_TEXT.length * 2; // 2 frames/char

export const S08_DescriptionMagic: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Camera shift DOWN to description
  const cameraProgress = spring({ frame, fps, config: { damping: 20, stiffness: 80 } });
  const cameraY = interpolate(cameraProgress, [0, 1], [0, 30]);

  // Magic button glow pulse (starts at frame TYPING_END + 5)
  const glowFrame = TYPING_END + 5;
  const glowProgress = spring({ frame: frame - glowFrame, fps, config: { damping: 30 } });
  const glowSize = interpolate(glowProgress, [0, 1], [0, 20]);

  // Click at frame TYPING_END + 25
  const clickFrame = TYPING_END + 25;
  const clickProgress = spring({
    frame: frame - clickFrame,
    fps,
    config: { damping: 30, stiffness: 400 },
    durationInFrames: 15,
  });
  const btnScale = frame >= clickFrame
    ? interpolate(clickProgress, [0, 0.5, 1], [1, 0.92, 1.0])
    : 1;

  // Ripple
  const rippleProgress = spring({ frame: frame - clickFrame, fps, config: { damping: 200 }, durationInFrames: 20 });

  // Cursor positions
  const cursorPositions = [
    { x: 0, y: 0, frame: 0 },
    { x: 0, y: 0, frame: TYPING_END },
    { x: 360, y: -100, frame: TYPING_END + 20 }, // move to magic button
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
            transform: `scale(1.4) translateY(${cameraY}px)`,
            transformOrigin: "center center",
            position: "relative",
          }}
        >
          {/* Modal */}
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
            <div style={{ padding: "20px 24px", borderBottom: "1px solid #27272a" }}>
              <span style={{ color: "white", fontSize: 18, fontWeight: 600, fontFamily: FONTS.body }}>
                Create Workflow
              </span>
            </div>

            <div style={{ flex: 1, display: "flex" }}>
              <div style={{ flex: 1, padding: 24, display: "flex", flexDirection: "column", gap: 20, borderRight: "1px solid #27272a" }}>
                {/* Title — completed */}
                <div>
                  <div style={{ fontSize: 13, color: "#a1a1aa", marginBottom: 8, fontFamily: FONTS.body }}>Workflow Name</div>
                  <div style={{ background: "#27272a", border: "1px solid #3f3f46", borderRadius: 8, padding: "10px 14px", color: "white", fontSize: 15, fontFamily: FONTS.body }}>
                    Daily Email Digest &amp; Briefing
                  </div>
                </div>

                {/* Description — being typed */}
                <div>
                  <div style={{ fontSize: 13, color: "#a1a1aa", marginBottom: 8, fontFamily: FONTS.body }}>Description</div>
                  <div
                    style={{
                      background: "#27272a",
                      border: `1px solid ${COLORS.primary}66`,
                      borderRadius: 8,
                      padding: "10px 14px",
                      color: "white",
                      fontSize: 15,
                      height: 100,
                      fontFamily: FONTS.body,
                      boxShadow: `0 0 0 2px ${COLORS.primary}22`,
                      position: "relative",
                    }}
                  >
                    <TypingText text={DESC_TEXT} framesPerChar={2} delay={0} />

                    {/* Magic/wand button */}
                    <div
                      style={{
                        position: "absolute",
                        right: 10,
                        bottom: 10,
                        width: 32,
                        height: 32,
                        borderRadius: 8,
                        background: "#3f3f46",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        fontSize: 16,
                        boxShadow: frame >= glowFrame ? `0 0 ${glowSize}px ${COLORS.primary}` : "none",
                        transform: `scale(${btnScale})`,
                        cursor: "pointer",
                      }}
                    >
                      ✨
                    </div>

                    {/* Click ripple */}
                    {frame >= clickFrame && (
                      <div
                        style={{
                          position: "absolute",
                          right: 26,
                          bottom: 26,
                          width: 100,
                          height: 100,
                          borderRadius: "50%",
                          background: `rgba(0, 187, 255, 0.3)`,
                          transform: `translate(50%, 50%) scale(${rippleProgress * 2})`,
                          opacity: Math.max(0, 1 - rippleProgress),
                          pointerEvents: "none",
                        }}
                      />
                    )}
                  </div>
                </div>

                {/* Triggers */}
                <div>
                  <div style={{ fontSize: 13, color: "#a1a1aa", marginBottom: 8, fontFamily: FONTS.body }}>Trigger</div>
                  <div style={{ display: "flex", gap: 8 }}>
                    {["Manual", "Schedule", "Event"].map((tab, i) => (
                      <div key={i} style={{ padding: "6px 14px", borderRadius: 6, background: i === 0 ? "#3f3f46" : "transparent", border: "1px solid #3f3f46", color: i === 0 ? "white" : "#71717a", fontSize: 13, fontFamily: FONTS.body }}>
                        {tab}
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              {/* Right panel */}
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
              <div style={{ padding: "10px 20px", borderRadius: 8, border: "1px solid #3f3f46", color: "#a1a1aa", fontSize: 14, fontFamily: FONTS.body }}>Cancel</div>
              <div style={{ padding: "10px 24px", borderRadius: 8, background: COLORS.primary, color: "#000", fontSize: 14, fontWeight: 700, fontFamily: FONTS.body }}>Create Workflow</div>
            </div>
          </div>

          {/* Cursor dot */}
          <CursorDot positions={cursorPositions} clickFrame={clickFrame} />
        </div>
      </div>
    </AbsoluteFill>
  );
};
