import {
  DateTimeIcon,
  GitForkIcon,
  LayersIcon,
  UserCircle02Icon,
} from "@theexperiencecompany/gaia-icons/solid-rounded";
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

// Stat chip matching the actual marketplace page design
const StatChip: React.FC<{
  icon: React.ReactNode;
  label: string;
  value: string;
  delay: number;
}> = ({ icon, label, value, delay }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = spring({ frame: frame - delay, fps, config: { damping: 200 } });
  const opacity = interpolate(p, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });
  const y = interpolate(p, [0, 1], [12, 0]);

  return (
    <div
      style={{
        opacity,
        transform: `translateY(${y}px)`,
        display: "flex",
        alignItems: "center",
        gap: 10,
        background: "rgba(24,24,27,0.7)",
        backdropFilter: "blur(8px)",
        borderRadius: 25,
        padding: "18px 26px",
      }}
    >
      <span style={{ color: "#71717a", display: "flex", flexShrink: 0 }}>
        {icon}
      </span>
      <div>
        <div style={{ fontFamily: FONTS.body, fontSize: 18, color: "#71717a" }}>
          {label}
        </div>
        <div
          style={{
            fontFamily: FONTS.body,
            fontSize: 22,
            color: "#d4d4d8",
            fontWeight: 500,
          }}
        >
          {value}
        </div>
      </div>
    </div>
  );
};

// Tool card in the tools grid
const ToolCard: React.FC<{
  name: string;
  description: string;
  delay: number;
}> = ({ name, description, delay }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = spring({ frame: frame - delay, fps, config: { damping: 200 } });
  const opacity = interpolate(p, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });
  const y = interpolate(p, [0, 1], [10, 0]);

  return (
    <div
      style={{
        opacity,
        transform: `translateY(${y}px)`,
        background: "rgba(39,39,42,0.5)",
        borderRadius: 12,
        padding: "16px 18px",
      }}
    >
      <p
        style={{
          fontFamily: FONTS.body,
          fontSize: 22,
          fontWeight: 500,
          color: "#e4e4e7",
          margin: "0 0 4px",
        }}
      >
        {name}
      </p>
      <p
        style={{
          fontFamily: FONTS.body,
          fontSize: 19,
          color: "#a1a1aa",
          margin: 0,
          lineHeight: 1.4,
        }}
      >
        {description}
      </p>
    </div>
  );
};

const TOOLS = [
  {
    name: "Read Page",
    description: "Fetches full content and metadata from any Notion page",
  },
  {
    name: "Create Page",
    description: "Creates new pages in databases or as sub-pages",
  },
  {
    name: "Query Database",
    description: "Filters and sorts records from Notion databases",
  },
  {
    name: "Update Block",
    description: "Modifies existing blocks and content in pages",
  },
  {
    name: "Search Workspace",
    description: "Full-text search across all pages and databases",
  },
];

export const S26c_IntegrationPage: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Page slides up from below
  const pageP = spring({ frame, fps, config: { damping: 20, stiffness: 90 } });
  const pageY = interpolate(pageP, [0, 1], [50, 0]);
  const pageOpacity = interpolate(pageP, [0, 0.15], [0, 1], {
    extrapolateRight: "clamp",
  });

  // Breadcrumbs
  const breadcrumbP = spring({
    frame: frame - 8,
    fps,
    config: { damping: 200 },
  });
  const breadcrumbOpacity = interpolate(breadcrumbP, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });

  // Header content stagger
  const headerIconP = spring({
    frame: frame - 14,
    fps,
    config: { damping: 200 },
  });
  const titleP = spring({ frame: frame - 18, fps, config: { damping: 200 } });
  const descP = spring({ frame: frame - 25, fps, config: { damping: 200 } });
  const btnP = spring({
    frame: frame - 22,
    fps,
    config: { damping: 18, stiffness: 120 },
  });

  const itemOpacity = (p: number) =>
    interpolate(p, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });
  const itemY = (p: number) => interpolate(p, [0, 1], [16, 0]);

  // RaisedButton scale punch
  const btnScale = interpolate(btnP, [0, 0.5, 1], [0.88, 1.05, 1.0]);

  // Card entrance
  const cardP = spring({
    frame: frame - 60,
    fps,
    config: { damping: 20, stiffness: 100 },
  });
  const cardOpacity = interpolate(cardP, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });
  const cardY = interpolate(cardP, [0, 1], [20, 0]);

  return (
    <AbsoluteFill style={{ background: "#09090b", overflow: "hidden" }}>
      {/* Cyan radial glow */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          background:
            "radial-gradient(ellipse 80% 60% at 50% 0%, rgba(0,187,255,0.04) 0%, transparent 70%)",
        }}
      />

      {/* Centered content — max-w-5xl */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          justifyContent: "center",
          alignItems: "center",
          padding: "16px 24px",
        }}
      >
        <div
          style={{
            width: "100%",
            maxWidth: 1300,
            display: "flex",
            flexDirection: "column",
            gap: 28,
            transform: `translateY(${pageY}px)`,
            opacity: pageOpacity,
          }}
        >
          {/* Breadcrumbs */}
          <div
            style={{
              opacity: breadcrumbOpacity,
              display: "flex",
              alignItems: "center",
              gap: 6,
              fontFamily: FONTS.body,
              fontSize: 18,
              color: "#52525b",
            }}
          >
            <span>Home</span>
            <span>/</span>
            <span>Marketplace</span>
            <span>/</span>
            <span style={{ color: "#a1a1aa" }}>Productivity</span>
          </div>

          {/* Header row */}
          <div
            style={{
              display: "flex",
              alignItems: "flex-start",
              justifyContent: "space-between",
              gap: 24,
            }}
          >
            <div style={{ flex: 1 }}>
              {/* Icon + Title */}
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 20,
                  opacity: itemOpacity(headerIconP),
                  transform: `translateY(${itemY(headerIconP)}px)`,
                }}
              >
                <div
                  style={{
                    width: 76,
                    height: 76,
                    minWidth: 76,
                    borderRadius: 12,
                    background: "#27272a",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    overflow: "hidden",
                  }}
                >
                  <Img
                    src={staticFile("images/icons/notion.webp")}
                    style={{ width: 56, height: 56, objectFit: "contain" }}
                  />
                </div>
                <h1
                  style={{
                    fontFamily: FONTS.body,
                    fontSize: 72,
                    fontWeight: 500,
                    color: "#fafafa",
                    margin: 0,
                    lineHeight: 1.1,
                    opacity: itemOpacity(titleP),
                    transform: `translateY(${itemY(titleP)}px)`,
                  }}
                >
                  Notion
                </h1>
              </div>

              {/* Description */}
              <p
                style={{
                  fontFamily: FONTS.body,
                  fontSize: 28,
                  color: "#71717a",
                  margin: "20px 0 0",
                  lineHeight: 1.6,
                  maxWidth: 700,
                  opacity: itemOpacity(descP),
                  transform: `translateY(${itemY(descP)}px)`,
                }}
              >
                Connect your Notion workspace to read pages, query databases,
                and create new content with AI
              </p>
            </div>

            {/* RaisedButton — "Add to your GAIA" */}
            <div
              style={{
                opacity: itemOpacity(btnP),
                transform: `scale(${btnScale})`,
                flexShrink: 0,
                marginTop: 8,
              }}
            >
              <div
                style={{
                  fontFamily: FONTS.body,
                  fontSize: 22,
                  fontWeight: 600,
                  color: "#000",
                  background: COLORS.primary,
                  borderRadius: 14,
                  padding: "16px 32px",
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  whiteSpace: "nowrap",
                  boxShadow:
                    "0 4px 5px 0px rgba(0,187,255,0.25), 0 0 0 1px rgba(0,187,255,0.4), inset 0 1px 0 rgba(255,255,255,0.25)",
                  cursor: "pointer",
                }}
              >
                Add to your GAIA
              </div>
            </div>
          </div>

          {/* Stats chips row */}
          <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
            <StatChip
              icon={
                <LayersIcon
                  width={26}
                  height={26}
                  style={{ color: "#71717a" }}
                />
              }
              label="Category"
              value="Productivity"
              delay={35}
            />
            <StatChip
              icon={
                <Img
                  src="https://github.com/aryanranderiya.png"
                  style={{
                    width: 35,
                    height: 35,
                    borderRadius: "50%",
                    objectFit: "cover",
                    flexShrink: 0,
                  }}
                />
              }
              label="Created by"
              value="You"
              delay={42}
            />
            <StatChip
              icon={
                <GitForkIcon
                  width={26}
                  height={26}
                  style={{ color: "#71717a" }}
                />
              }
              label="Users"
              value="2,841"
              delay={49}
            />
            <StatChip
              icon={
                <DateTimeIcon
                  width={26}
                  height={26}
                  style={{ color: "#71717a" }}
                />
              }
              label="Published"
              value="just now"
              delay={56}
            />
          </div>

          {/* Tools card — bg-zinc-900/50 backdrop-blur-md rounded-3xl */}
          <div
            style={{
              background: "rgba(24,24,27,0.6)",
              backdropFilter: "blur(8px)",
              borderRadius: 24,
              overflow: "hidden",
              opacity: cardOpacity,
              transform: `translateY(${cardY}px)`,
            }}
          >
            {/* CardHeader */}
            <div style={{ padding: "24px 32px 14px" }}>
              <h2
                style={{
                  fontFamily: FONTS.body,
                  fontSize: 28,
                  fontWeight: 400,
                  color: "#f4f4f5",
                  margin: 0,
                }}
              >
                Available Tools ({TOOLS.length})
              </h2>
            </div>
            {/* CardBody — 2-col grid */}
            <div
              style={{
                padding: "8px 32px 32px",
                display: "grid",
                gridTemplateColumns: "1fr 1fr",
                gap: 16,
              }}
            >
              {TOOLS.map((tool, i) => (
                <ToolCard
                  key={tool.name}
                  name={tool.name}
                  description={tool.description}
                  delay={65 + i * 7}
                />
              ))}
            </div>
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};
