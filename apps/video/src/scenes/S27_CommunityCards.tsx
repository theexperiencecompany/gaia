import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig, spring, interpolate, Img, staticFile } from "remotion";
import { COLORS, FONTS } from "../constants";

const COMMUNITY_WORKFLOWS = [
  {
    title: "Daily Email Digest",
    description: "Summarizes Gmail each morning and posts to Slack.",
    icons: ["images/icons/gmail.svg", "images/icons/slack.svg", "images/icons/googledocs.webp"],
    uses: 1240,
    creator: "A",
  },
  {
    title: "GitHub Issue Tracker",
    description: "Monitors open PRs and posts daily updates to Slack.",
    icons: ["images/icons/github.svg", "images/icons/slack.svg", "images/icons/notion.webp"],
    uses: 876,
    creator: "B",
  },
  {
    title: "Calendar Prep Assistant",
    description: "Prepares meeting agendas from calendar events automatically.",
    icons: ["images/icons/googlecalendar.webp", "images/icons/googledocs.webp", "images/icons/gmail.svg"],
    uses: 2103,
    creator: "C",
  },
  {
    title: "Social Media Planner",
    description: "Schedules posts from Notion drafts to social channels.",
    icons: ["images/icons/notion.webp", "images/icons/slack.svg", "images/icons/googledocs.webp"],
    uses: 654,
    creator: "D",
  },
  {
    title: "Team Standup Bot",
    description: "Collects standups from Slack and summarizes in Notion.",
    icons: ["images/icons/slack.svg", "images/icons/notion.webp", "images/icons/googlecalendar.webp"],
    uses: 432,
    creator: "E",
  },
  {
    title: "Invoice Processor",
    description: "Extracts invoice data from Gmail and logs to Sheets.",
    icons: ["images/icons/gmail.svg", "images/icons/googlesheets.webp", "images/icons/googledocs.webp"],
    uses: 321,
    creator: "F",
  },
];

interface CommunityCardProps {
  workflow: (typeof COMMUNITY_WORKFLOWS)[number];
  index: number;
}

const CommunityCard: React.FC<CommunityCardProps> = ({ workflow, index }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const delay = index * 12;
  const progress = spring({ frame: frame - delay, fps, config: { damping: 20, stiffness: 120 } });
  const scale = interpolate(progress, [0, 1], [0.95, 1.0]);
  const opacity = interpolate(progress, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });
  const y = interpolate(progress, [0, 1], [30, 0]);

  return (
    <div style={{
      background: "#18181b",
      borderRadius: 28,
      padding: 28,
      display: "flex",
      flexDirection: "column",
      gap: 16,
      transform: `scale(${scale}) translateY(${y}px)`,
      opacity,
      minHeight: 240,
    }}>
      {/* Stacked tool icons */}
      <div style={{ display: "flex" }}>
        {workflow.icons.map((icon, i) => (
          <div key={i} style={{
            width: 44, height: 44, borderRadius: 12,
            background: "#27272a",
            border: "2px solid #18181b",
            display: "flex", alignItems: "center", justifyContent: "center",
            marginLeft: i > 0 ? -8 : 0,
            zIndex: workflow.icons.length - i,
            position: "relative", overflow: "hidden",
          }}>
            <Img src={staticFile(icon)} style={{ width: 28, height: 28, objectFit: "contain" }} />
          </div>
        ))}
      </div>

      {/* Title */}
      <div style={{ color: "white", fontFamily: FONTS.body, fontSize: 20, fontWeight: 600, lineHeight: 1.3 }}>
        {workflow.title}
      </div>

      {/* Description */}
      <div style={{ color: COLORS.zinc400, fontFamily: FONTS.body, fontSize: 16, lineHeight: 1.5, flex: 1 }}>
        {workflow.description}
      </div>

      {/* Footer */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 4 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <div style={{
            width: 32, height: 32, borderRadius: "50%",
            background: COLORS.primary + "33",
            display: "flex", alignItems: "center", justifyContent: "center",
            fontSize: 14, fontFamily: FONTS.body, fontWeight: 700, color: COLORS.primary,
          }}>
            {workflow.creator}
          </div>
          <span style={{ color: COLORS.zinc400, fontSize: 15, fontFamily: FONTS.body }}>
            {workflow.uses.toLocaleString()} uses
          </span>
        </div>
        <div style={{
          padding: "8px 20px", borderRadius: 12,
          background: COLORS.primary,
          color: "#000", fontSize: 16,
          fontFamily: FONTS.body, fontWeight: 600,
        }}>
          Use
        </div>
      </div>
    </div>
  );
};

export const S27_CommunityCards: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Header "Create. Publish. Browse." springs in at frame 0
  const headerProgress = spring({ frame, fps, config: { damping: 200 } });
  const headerOpacity = interpolate(headerProgress, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });
  const headerY = interpolate(headerProgress, [0, 1], [30, 0]);

  // Label fades in slightly after
  const labelProgress = spring({ frame, fps, config: { damping: 200 } });
  const labelOpacity = interpolate(labelProgress, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });

  return (
    <AbsoluteFill style={{ background: COLORS.bgLight, overflow: "hidden" }}>
      <div style={{
        position: "absolute",
        inset: 0,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        padding: "40px 80px",
        gap: 16,
      }}>
        {/* Header: Create. Publish. Browse. */}
        <div style={{
          transform: `translateY(${headerY}px)`,
          opacity: headerOpacity,
          textAlign: "center",
          lineHeight: 1.1,
        }}>
          <span style={{
            fontFamily: FONTS.display,
            fontSize: 100,
            fontWeight: 800,
            color: COLORS.textDark,
          }}>
            {"Create. "}
          </span>
          <span style={{
            fontFamily: FONTS.display,
            fontSize: 100,
            fontWeight: 800,
            color: COLORS.primary,
          }}>
            {"Publish. "}
          </span>
          <span style={{
            fontFamily: FONTS.display,
            fontSize: 100,
            fontWeight: 800,
            color: COLORS.textDark,
          }}>
            Browse.
          </span>
        </div>

        {/* Cards grid */}
        <div style={{
          display: "grid",
          gridTemplateColumns: "repeat(3, 1fr)",
          gap: 16,
          width: "100%",
          maxWidth: 1400,
        }}>
          {COMMUNITY_WORKFLOWS.map((workflow, i) => (
            <CommunityCard key={i} workflow={workflow} index={i} />
          ))}
        </div>
      </div>
    </AbsoluteFill>
  );
};
