import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig, spring, interpolate, Img, staticFile } from "remotion";
import { COLORS, FONTS } from "../constants";
import { SceneBackground } from "../components/SceneBackground";
import { WorkflowVideoCard } from "../components/WorkflowVideoCard";

const TOOL_ICONS = [
  "images/icons/gmail.svg",
  "images/icons/googlecalendar.webp",
  "images/icons/github.svg",
  "images/icons/slack.svg",
];
const ROTATIONS = [8, -8, 5, -5];

export const S17_RunningToolStack: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Tool calls block slides up
  const toolsProgress = spring({ frame, fps, config: { damping: 25 } });
  const toolsY = interpolate(toolsProgress, [0, 1], [30, 0]);
  const toolsOpacity = interpolate(toolsProgress, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });

  // "Used 4 tools" label at frame 32
  const labelProgress = spring({ frame: frame - 32, fps, config: { damping: 200 } });
  const labelOpacity = interpolate(labelProgress, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });

  const spinAngle = interpolate(frame, [0, 60], [0, 360]);

  return (
    <AbsoluteFill>
      <SceneBackground variant="light" />
      <div
        style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <div style={{ width: 700, display: "flex", flexDirection: "column", gap: 28, transform: "scale(1.2)", transformOrigin: "center center" }}>
          {/* WorkflowVideoCard */}
          <WorkflowVideoCard
            title="Daily Morning Briefing"
            schedule="Every day at 8:00 AM"
            status="running"
          />

          {/* Tool calls block */}
          <div
            style={{
              width: 700,
              background: "#18181b",
              borderRadius: 20,
              padding: "24px 28px",
              transform: `translateY(${toolsY}px)`,
              opacity: toolsOpacity,
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16 }}>
              {/* Stacked real icons */}
              <div style={{ display: "flex", alignItems: "center" }}>
                {TOOL_ICONS.map((icon, i) => {
                  const iconProgress = spring({
                    frame: frame - i * 8,
                    fps,
                    config: { damping: 200 },
                  });
                  const iconScale = interpolate(iconProgress, [0, 1], [0, 1]);
                  const iconX = interpolate(iconProgress, [0, 1], [24, i * -10]);

                  return (
                    <div
                      key={i}
                      style={{
                        width: 56,
                        height: 56,
                        borderRadius: 12,
                        background: "#27272a",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        overflow: "hidden",
                        transform: `translateX(${iconX}px) rotate(${ROTATIONS[i]}deg) scale(${iconScale})`,
                        zIndex: TOOL_ICONS.length - i,
                        position: "relative",
                      }}
                    >
                      <Img
                        src={staticFile(icon)}
                        style={{ width: 36, height: 36, objectFit: "contain", filter: icon.includes("github") ? "invert(1)" : undefined }}
                      />
                      {/* Spinning loader on last icon */}
                      {i === TOOL_ICONS.length - 1 && (
                        <div
                          style={{
                            position: "absolute",
                            inset: -3,
                            borderRadius: 15,
                            border: "2.5px solid transparent",
                            borderTopColor: COLORS.primary,
                            transform: `rotate(${spinAngle}deg)`,
                          }}
                        />
                      )}
                    </div>
                  );
                })}
              </div>

              <span style={{ color: "#a1a1aa", fontFamily: FONTS.body, fontSize: 28, fontWeight: 500, marginLeft: 16, opacity: labelOpacity }}>
                Used 4 tools
              </span>
            </div>

            <div style={{ color: "#a1a1aa", fontFamily: FONTS.body, fontSize: 24 }}>
              Fetching emails, calendar, GitHub, and Slack...
            </div>
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};
