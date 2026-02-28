import React from "react";
import {
  AbsoluteFill,
  useCurrentFrame,
  useVideoConfig,
  spring,
  interpolate,
  Img,
  staticFile,
} from "remotion";
import { CheckmarkCircle02Icon } from "@theexperiencecompany/gaia-icons/solid-rounded";
import { COLORS, FONTS } from "../constants";
import { UserTail } from "./S06_UserChat";

const USER_MESSAGE =
  "Hey GAIA — pull my Gmail from the last 6 hours, check Google Calendar for today's meetings, scan my GitHub for open PRs, and check Slack for anything urgent. Summarize everything and set this up to run every morning at 8am automatically.";

const TOOLS = [
  { icon: "images/icons/gmail.svg", name: "Fetch emails", category: "Gmail", completeAt: 12 },
  { icon: "images/icons/googlecalendar.webp", name: "Get calendar events", category: "Google Calendar", completeAt: 24 },
  { icon: "images/icons/github.svg", name: "List pull requests", category: "GitHub", completeAt: 36 },
  { icon: "images/icons/slack.svg", name: "Fetch messages", category: "Slack", completeAt: 48 },
  { icon: "images/icons/notion.webp", name: "Create todos", category: "Notion", completeAt: 60 },
  { icon: "images/icons/googledocs.webp", name: "Write briefing", category: "Google Docs", completeAt: 72 },
];

const ROTATIONS = [8, -8, 5, -5, 7, -6];

interface ToolRowProps {
  tool: (typeof TOOLS)[number];
  index: number;
}

const ToolRow: React.FC<ToolRowProps> = ({ tool, index }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const rowDelay = index * 8;
  const rowProgress = spring({ frame: frame - rowDelay, fps, config: { damping: 200 } });
  const rowOpacity = interpolate(rowProgress, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });
  const rowY = interpolate(rowProgress, [0, 1], [12, 0]);

  const isDone = frame >= tool.completeAt;
  const spinAngle = interpolate(frame, [0, 60], [0, 360]);

  const successProgress = spring({ frame: frame - tool.completeAt, fps, config: { damping: 12 } });
  const successScale = isDone ? interpolate(successProgress, [0, 0.5, 1], [0, 1.3, 1.0]) : 0;

  return (
    <div style={{ opacity: rowOpacity, transform: `translateY(${rowY}px)`, display: "flex", gap: 12 }}>
      {/* LEFT: icon + connector line */}
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
        <div
          style={{
            width: 36,
            height: 36,
            borderRadius: 10,
            background: "#27272a",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            flexShrink: 0,
            overflow: "hidden",
          }}
        >
          <Img src={staticFile(tool.icon)} style={{ width: 22, height: 22, objectFit: "contain", filter: tool.icon.includes("github") ? "invert(1)" : undefined }} />
        </div>
        {/* Vertical connector (not on last row) */}
        {index < TOOLS.length - 1 && (
          <div style={{ width: 1, flex: 1, background: "#3f3f46", minHeight: 16, marginTop: 4 }} />
        )}
      </div>

      {/* RIGHT: name + category */}
      <div style={{ flex: 1, paddingTop: 4, paddingBottom: index < TOOLS.length - 1 ? 16 : 0 }}>
        <div style={{ color: "#a1a1aa", fontSize: 20, fontFamily: FONTS.body, fontWeight: 500 }}>
          {tool.name}
        </div>
        <div style={{ color: "#71717a", fontSize: 16, fontFamily: FONTS.body, marginTop: 2 }}>
          {tool.category}
        </div>
      </div>

      {/* Status */}
      <div style={{ width: 28, height: 28, display: "flex", alignItems: "center", justifyContent: "center", paddingTop: 4 }}>
        {isDone ? (
          <CheckmarkCircle02Icon size={24} style={{ display: "inline-block", transform: `scale(${successScale})`, color: "#22c55e" }} />
        ) : (
          <div style={{ width: 20, height: 20, borderRadius: "50%", border: "2.5px solid transparent", borderTopColor: COLORS.primary, transform: `rotate(${spinAngle}deg)` }} />
        )}
      </div>
    </div>
  );
};

export const S07_ChatToolCalls: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const blockProgress = spring({ frame, fps, config: { damping: 22 } });
  const blockY = interpolate(blockProgress, [0, 1], [24, 0]);
  const blockOpacity = interpolate(blockProgress, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });

  const accordionProgress = spring({ frame: frame - 20, fps, config: { damping: 10, stiffness: 90 } });
  // Start at 82px so the header ("Used N tools") is always fully visible when collapsed
  const accordionMaxH = interpolate(accordionProgress, [0, 1], [82, 820]);

  // Exit: slide up + fade (clears for slide-from-bottom transition)
  const exitP = spring({ frame: frame - 88, fps, config: { damping: 200 } });
  const exitY = interpolate(exitP, [0, 1], [0, -30], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const exitOpacity = interpolate(exitP, [0, 1], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

  return (
    <AbsoluteFill style={{ background: COLORS.bgLight, display: "flex", alignItems: "center", justifyContent: "center", transform: `translateY(${exitY}px)`, opacity: exitOpacity }}>
      <div style={{ width: 1400, display: "flex", flexDirection: "column", gap: 32 }}>

        {/* User message (static, faded as context) */}
        <div style={{ display: "flex", justifyContent: "flex-end", paddingRight: 32, opacity: 0.5 }}>
          <div style={{ position: "relative" }}>
            <div style={{ background: COLORS.primary, color: "#000", padding: "14px 28px", borderRadius: "40px 40px 8px 40px", fontSize: 26, lineHeight: 1.5, fontWeight: 500, fontFamily: FONTS.body, maxWidth: 900 }}>
              {USER_MESSAGE}
            </div>
            <UserTail bg={COLORS.primary} bgColor={COLORS.bgLight} />
          </div>
        </div>

        {/* GAIA tool calls — main content */}
        <div style={{ display: "flex", alignItems: "flex-end", gap: 20, paddingLeft: 8, transform: `translateY(${blockY}px)`, opacity: blockOpacity }}>
          <Img
            src={staticFile("images/logos/logo.webp")}
            style={{ width: 60, height: 60, borderRadius: "50%", objectFit: "contain", flexShrink: 0 }}
          />

          {/* ToolCallsSection — accordion style matching web app */}
          <div style={{ background: "#18181b", borderRadius: 28, padding: "24px 32px", width: 700, overflow: "hidden", maxHeight: `${accordionMaxH}px` }}>
            {/* Accordion header */}
            <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 20 }}>
              {/* Stacked icons */}
              <div style={{ display: "flex", alignItems: "center" }}>
                {TOOLS.map((tool, i) => {
                  const iconProgress = spring({ frame: frame - i * 8, fps, config: { damping: 200 } });
                  const iconScale = interpolate(iconProgress, [0, 1], [0, 1]);
                  return (
                    <div
                      key={i}
                      style={{
                        width: 40,
                        height: 40,
                        borderRadius: 10,
                        background: "#27272a",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        overflow: "hidden",
                        marginLeft: i > 0 ? -10 : 0,
                        zIndex: TOOLS.length - i,
                        position: "relative",
                        transform: `rotate(${ROTATIONS[i]}deg) scale(${iconScale})`,
                      }}
                    >
                      <Img src={staticFile(tool.icon)} style={{ width: 24, height: 24, objectFit: "contain", filter: tool.icon.includes("github") ? "invert(1)" : undefined }} />
                    </div>
                  );
                })}
              </div>
              <span style={{ color: "#a1a1aa", fontFamily: FONTS.body, fontSize: 22, fontWeight: 500, marginLeft: 10 }}>
                Used {TOOLS.length} tools
              </span>
              <span style={{ color: COLORS.zinc500, fontSize: 24, marginLeft: "auto" }}>›</span>
            </div>

            {/* Tool rows */}
            <div>
              {TOOLS.map((tool, i) => <ToolRow key={i} tool={tool} index={i} />)}
            </div>
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};
