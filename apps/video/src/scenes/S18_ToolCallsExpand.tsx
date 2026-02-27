import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig, spring, interpolate, Img, staticFile } from "remotion";
import { COLORS, FONTS } from "../constants";
import { SceneBackground } from "../components/SceneBackground";
import { WorkflowVideoCard } from "../components/WorkflowVideoCard";

const ROTATIONS = [8, -8, 5, -5];

const TOOL_CALLS = [
  { icon: "images/icons/gmail.svg", name: "Fetch emails", category: "Gmail", status: "success" as const },
  { icon: "images/icons/googlecalendar.webp", name: "Get calendar events", category: "Calendar", status: "success" as const },
  { icon: "images/icons/github.svg", name: "List pull requests", category: "GitHub", status: "success" as const },
  { icon: "images/icons/slack.svg", name: "Fetch messages", category: "Slack", status: "running" as const },
];

interface ToolRowProps {
  tool: (typeof TOOL_CALLS)[number];
  index: number;
  accordionProgress: number;
}

const ToolRow: React.FC<ToolRowProps> = ({ tool, index, accordionProgress }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const delay = index * 10;
  const rowProgress = spring({ frame: frame - delay, fps, config: { damping: 200 } });
  const rowOpacity = interpolate(rowProgress, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });

  const successProgress = spring({ frame: frame - 60, fps, config: { damping: 12 } });
  const successScale =
    tool.status === "running"
      ? interpolate(successProgress, [0, 0.5, 1], [0, 1.2, 1.0])
      : 0;
  const showSuccess = tool.status === "running" && frame >= 60;
  const spinAngle = interpolate(frame, [0, 60], [0, 360]);

  return (
    <div style={{ opacity: rowOpacity * accordionProgress, display: "flex", gap: 12 }}>
      {/* LEFT: icon + connector */}
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
        <div style={{ width: 32, height: 32, borderRadius: 8, background: "rgba(39,39,42,0.5)", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0, overflow: "hidden" }}>
          <Img src={staticFile(tool.icon)} style={{ width: 20, height: 20, objectFit: "contain", filter: tool.icon.includes("github") ? "invert(1)" : undefined }} />
        </div>
        {index < TOOL_CALLS.length - 1 && (
          <div style={{ width: 1, flex: 1, background: "#3f3f46", minHeight: 12, marginTop: 4 }} />
        )}
      </div>

      {/* RIGHT: name + category */}
      <div style={{ flex: 1, paddingTop: 4, paddingBottom: index < TOOL_CALLS.length - 1 ? 14 : 0 }}>
        <div style={{ color: "#a1a1aa", fontSize: 18, fontFamily: FONTS.body, fontWeight: 500 }}>
          {tool.name}
        </div>
        <div style={{ color: "#71717a", fontSize: 14, fontFamily: FONTS.body, marginTop: 2 }}>
          {tool.category}
        </div>
      </div>

      {/* Status */}
      <div style={{ width: 24, height: 24, display: "flex", alignItems: "center", justifyContent: "center", paddingTop: 4 }}>
        {tool.status === "success" && <span style={{ color: "#22c55e", fontSize: 18 }}>✓</span>}
        {tool.status === "running" && !showSuccess && (
          <div style={{ width: 18, height: 18, borderRadius: "50%", border: "2.5px solid transparent", borderTopColor: COLORS.primary, transform: `rotate(${spinAngle}deg)` }} />
        )}
        {showSuccess && <span style={{ color: "#22c55e", fontSize: 18, display: "inline-block", transform: `scale(${successScale})` }}>✓</span>}
      </div>
    </div>
  );
};

export const S18_ToolCallsExpand: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const accordionProgress = spring({ frame, fps, config: { damping: 20, stiffness: 100 } });

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
        <div style={{ width: 960, display: "flex", flexDirection: "column", gap: 24, overflowY: "hidden" }}>
          {/* WorkflowVideoCard */}
          <WorkflowVideoCard
            title="Daily Morning Briefing"
            schedule="Every day at 8:00 AM"
            status="running"
          />

          {/* Expanded tool calls — accordion style */}
          <div
            style={{
              background: "#18181b",
              borderRadius: 20,
              padding: "20px 28px",
              overflow: "hidden",
              maxHeight: `${accordionProgress * 400}px`,
            }}
          >
            {/* Accordion header */}
            <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 16 }}>
              <div style={{ display: "flex", alignItems: "center" }}>
                {TOOL_CALLS.map((tool, i) => (
                  <div
                    key={i}
                    style={{
                      width: 36,
                      height: 36,
                      borderRadius: 9,
                      background: "#27272a",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      overflow: "hidden",
                      marginLeft: i > 0 ? -8 : 0,
                      zIndex: TOOL_CALLS.length - i,
                      position: "relative",
                      transform: `rotate(${ROTATIONS[i]}deg)`,
                    }}
                  >
                    <Img src={staticFile(tool.icon)} style={{ width: 22, height: 22, objectFit: "contain", filter: tool.icon.includes("github") ? "invert(1)" : undefined }} />
                  </div>
                ))}
              </div>
              <span style={{ color: "#a1a1aa", fontFamily: FONTS.body, fontSize: 20, fontWeight: 500, marginLeft: 8 }}>
                Used {TOOL_CALLS.length} tools
              </span>
              <span style={{ color: COLORS.zinc500, fontSize: 22, marginLeft: "auto" }}>›</span>
            </div>
            {TOOL_CALLS.map((tool, i) => (
              <ToolRow key={i} tool={tool} index={i} accordionProgress={accordionProgress} />
            ))}
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};
