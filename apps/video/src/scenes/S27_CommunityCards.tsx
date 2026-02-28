import type React from "react";
import {
  AbsoluteFill,
  Img,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { COLORS, FONTS } from "../constants";

const ROTATIONS = [8, -8, 5];

const COMMUNITY_WORKFLOWS = [
  {
    title: "Daily Email Digest",
    description: "Summarizes Gmail each morning and posts to Slack.",
    icons: [
      "images/icons/gmail.svg",
      "images/icons/slack.svg",
      "images/icons/googledocs.webp",
    ],
    uses: 1240,
    creator: "A",
    photo: "images/avatars/user1.jpg",
    name: "Sarah Chen",
  },
  {
    title: "GitHub Issue Tracker",
    description: "Monitors open PRs and posts daily updates to Slack.",
    icons: [
      "images/icons/github.svg",
      "images/icons/slack.svg",
      "images/icons/notion.webp",
    ],
    uses: 876,
    creator: "B",
    photo: "images/avatars/user2.jpg",
    name: "James Park",
  },
  {
    title: "Calendar Prep Assistant",
    description: "Prepares meeting agendas from calendar events automatically.",
    icons: [
      "images/icons/googlecalendar.webp",
      "images/icons/googledocs.webp",
      "images/icons/gmail.svg",
    ],
    uses: 2103,
    creator: "C",
    photo: "images/avatars/user3.jpg",
    name: "Mia Torres",
  },
  {
    title: "Social Media Planner",
    description: "Schedules posts from Notion drafts to social channels.",
    icons: [
      "images/icons/notion.webp",
      "images/icons/slack.svg",
      "images/icons/googledocs.webp",
    ],
    uses: 654,
    creator: "D",
    photo: "images/avatars/user4.jpg",
    name: "Alex Kim",
  },
  {
    title: "Team Standup Bot",
    description: "Collects standups from Slack and summarizes in Notion.",
    icons: [
      "images/icons/slack.svg",
      "images/icons/notion.webp",
      "images/icons/googlecalendar.webp",
    ],
    uses: 432,
    creator: "E",
    photo: "images/avatars/user5.jpg",
    name: "Priya Nair",
  },
  {
    title: "Invoice Processor",
    description: "Extracts invoice data from Gmail and logs to Sheets.",
    icons: [
      "images/icons/gmail.svg",
      "images/icons/googlesheets.webp",
      "images/icons/googledocs.webp",
    ],
    uses: 321,
    creator: "F",
    photo: "images/avatars/user6.jpg",
    name: "Lucas Müller",
  },
];

interface CommunityCardProps {
  workflow: (typeof COMMUNITY_WORKFLOWS)[number] & {
    photo: string;
    name: string;
  };
  index: number;
}

const CommunityCard: React.FC<CommunityCardProps> = ({ workflow, index }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const delay = index * 6;
  const progress = spring({
    frame: frame - delay,
    fps,
    config: { damping: 18, stiffness: 180 },
  });
  const scale = interpolate(progress, [0, 0.6, 1], [0.88, 1.04, 1.0]);
  const opacity = interpolate(progress, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });
  const y = interpolate(progress, [0, 1], [40, 0]);

  return (
    <div
      style={{
        background: "#1e1e21",
        borderRadius: 36,
        padding: "32px 28px",
        display: "flex",
        flexDirection: "column",
        gap: 16,
        transform: `scale(${scale}) translateY(${y}px)`,
        opacity,
        minHeight: 240,
      }}
    >
      {/* Stacked tool icons */}
      <div style={{ display: "flex" }}>
        {workflow.icons.map((icon, i) => (
          <div
            key={i}
            style={{
              width: 52,
              height: 52,
              borderRadius: 14,
              background: "#27272a",
              border: "2px solid #1e1e21",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              marginLeft: i > 0 ? -8 : 0,
              zIndex: workflow.icons.length - i,
              position: "relative",
              overflow: "hidden",
              transform: `rotate(${ROTATIONS[i] ?? 0}deg)`,
            }}
          >
            <Img
              src={staticFile(icon)}
              style={{
                width: 34,
                height: 34,
                objectFit: "contain",
                filter: icon.includes("github") ? "invert(1)" : undefined,
              }}
            />
          </div>
        ))}
      </div>

      {/* Title */}
      <div
        style={{
          color: "white",
          fontFamily: FONTS.body,
          fontSize: 26,
          fontWeight: 700,
          lineHeight: 1.3,
        }}
      >
        {workflow.title}
      </div>

      {/* Description */}
      <div
        style={{
          color: "#a1a1aa",
          fontFamily: FONTS.body,
          fontSize: 20,
          lineHeight: 1.5,
          flex: 1,
        }}
      >
        {workflow.description}
      </div>

      {/* Footer */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginTop: 4,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <Img
            src={staticFile(workflow.photo)}
            style={{
              width: 38,
              height: 38,
              borderRadius: "50%",
              objectFit: "cover",
              flexShrink: 0,
            }}
          />
          <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
            <span
              style={{
                color: "white",
                fontSize: 17,
                fontFamily: FONTS.body,
                fontWeight: 600,
              }}
            >
              {workflow.name}
            </span>
            <span
              style={{ color: "#71717a", fontSize: 15, fontFamily: FONTS.body }}
            >
              {workflow.uses.toLocaleString()} uses
            </span>
          </div>
        </div>
        <div
          style={{
            padding: "10px 24px",
            borderRadius: 14,
            background: COLORS.primary,
            color: "#000",
            fontSize: 20,
            fontFamily: FONTS.body,
            fontWeight: 700,
          }}
        >
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
  const headerOpacity = interpolate(headerProgress, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });
  const headerY = interpolate(headerProgress, [0, 1], [30, 0]);

  // Label fades in slightly after
  const labelProgress = spring({ frame, fps, config: { damping: 200 } });
  const labelOpacity = interpolate(labelProgress, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });

  // Animated counter: 0 → 2400 over frames 10–60
  const rawCount = interpolate(frame, [10, 60], [0, 2400], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const displayCount = Math.round(rawCount / 50) * 50;

  const counterProgress = spring({
    frame: frame - 10,
    fps,
    config: { damping: 200 },
  });
  const counterOpacity = interpolate(counterProgress, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill style={{ background: COLORS.bgLight, overflow: "hidden" }}>
      <div
        style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          padding: "40px 80px",
          gap: 20,
        }}
      >
        {/* Header: Create. Publish. Browse. */}
        <div
          style={{
            transform: `translateY(${headerY}px)`,
            opacity: headerOpacity,
            textAlign: "center",
            lineHeight: 1.1,
          }}
        >
          <span
            style={{
              fontFamily: FONTS.display,
              textTransform: "uppercase" as const,
              fontSize: 80,
              fontWeight: 700,
              color: COLORS.textDark,
            }}
          >
            {"Create. "}
          </span>
          <span
            style={{
              fontFamily: FONTS.display,
              textTransform: "uppercase" as const,
              fontSize: 80,
              fontWeight: 700,
              color: COLORS.primary,
            }}
          >
            {"Publish. "}
          </span>
          <span
            style={{
              fontFamily: FONTS.display,
              textTransform: "uppercase" as const,
              fontSize: 80,
              fontWeight: 700,
              color: COLORS.textDark,
            }}
          >
            Browse.
          </span>
        </div>

        {/* Animated counter */}
        <div style={{ opacity: counterOpacity, textAlign: "center" }}>
          <span
            style={{
              fontFamily: FONTS.body,
              fontSize: 40,
              color: COLORS.zinc600,
              fontWeight: 500,
            }}
          >
            {displayCount.toLocaleString()}+ community workflows
          </span>
        </div>

        {/* Cards grid */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(3, 1fr)",
            gap: 16,
            width: "100%",
            maxWidth: 1700,
          }}
        >
          {COMMUNITY_WORKFLOWS.map((workflow, i) => (
            <CommunityCard key={i} workflow={workflow} index={i} />
          ))}
        </div>
      </div>
    </AbsoluteFill>
  );
};
