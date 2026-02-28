import React from "react";
import {
  AbsoluteFill,
  Audio,
  Sequence,
  useCurrentFrame,
  useVideoConfig,
  spring,
  interpolate,
  Img,
  staticFile,
} from "remotion";
import { CheckmarkCircle02Icon } from "@theexperiencecompany/gaia-icons/solid-rounded";
import { COLORS, FONTS } from "../constants";
import { SceneBackground } from "../components/SceneBackground";
import { WorkflowVideoCard } from "../components/WorkflowVideoCard";
import { SFX } from "../sfx";

const ROTATIONS = [8, -8, 5, -5, 7, -6];
const STAGGER_STEP = 7;
const ACCORDION_START = 42;

const TOOL_CALLS = [
  {
    icon: "images/icons/gmail.svg",
    name: "Fetch emails",
    category: "Gmail",
    status: "success" as const,
  },
  {
    icon: "images/icons/googlecalendar.webp",
    name: "Get calendar events",
    category: "Calendar",
    status: "success" as const,
  },
  {
    icon: "images/icons/github.svg",
    name: "List pull requests",
    category: "GitHub",
    status: "success" as const,
  },
  {
    icon: "images/icons/slack.svg",
    name: "Fetch messages",
    category: "Slack",
    status: "success" as const,
  },
  {
    icon: "images/icons/notion.webp",
    name: "Create todos",
    category: "Notion",
    status: "success" as const,
  },
  {
    icon: "images/icons/googledocs.webp",
    name: "Write briefing",
    category: "Google Docs",
    status: "running" as const,
    completeAt: 88,
  },
];

type ToolCall = (typeof TOOL_CALLS)[number] & { completeAt?: number };

interface ToolRowProps {
  tool: ToolCall;
  index: number;
  accordionProgress: number;
  isLast: boolean;
}

const ToolRow: React.FC<ToolRowProps> = ({
  tool,
  index,
  accordionProgress,
  isLast,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const rowProgress = spring({
    frame: frame - (ACCORDION_START + index * 6),
    fps,
    config: { damping: 200 },
  });
  const rowOpacity = interpolate(rowProgress, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });

  const spinAngle = interpolate(frame, [0, 60], [0, 360]);

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 16,
        opacity: rowOpacity * accordionProgress,
        position: "relative",
        paddingBottom: isLast ? 0 : 20,
      }}
    >
      {/* Icon + vertical connector */}
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          flexShrink: 0,
        }}
      >
        <div
          style={{
            width: 44,
            height: 44,
            background: "rgba(39, 39, 42, 0.5)",
            borderRadius: 11,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            overflow: "hidden",
          }}
        >
          <Img
            src={staticFile(tool.icon)}
            style={{
              width: 28,
              height: 28,
              objectFit: "contain",
              filter: tool.icon.includes("github") ? "invert(1)" : undefined,
            }}
          />
        </div>
        {!isLast && (
          <div
            style={{
              width: 1,
              flex: 1,
              minHeight: 20,
              background: "rgba(63, 63, 70, 0.6)",
              marginTop: 4,
            }}
          />
        )}
      </div>

      {/* Tool info */}
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 2,
          flex: 1,
        }}
      >
        <span
          style={{
            color: "#a1a1aa",
            fontFamily: FONTS.body,
            fontSize: 24,
            fontWeight: 500,
            lineHeight: 1.2,
          }}
        >
          {tool.name}
        </span>
        <span
          style={{
            color: "#71717a",
            fontFamily: FONTS.body,
            fontSize: 20,
            lineHeight: 1.2,
          }}
        >
          {tool.category}
        </span>
      </div>

      {/* Status indicator */}
      <div style={{ flexShrink: 0 }}>
        {tool.status === "success" || (tool.completeAt !== undefined && frame >= tool.completeAt) ? (
          <CheckmarkCircle02Icon
            style={{ width: 28, height: 28, color: COLORS.primary }}
          />
        ) : (
          <div
            style={{
              width: 28,
              height: 28,
              borderRadius: "50%",
              border: "2.5px solid transparent",
              borderTopColor: COLORS.primary,
              borderRightColor: "rgba(99,102,241,0.3)",
              borderBottomColor: "rgba(99,102,241,0.3)",
              borderLeftColor: "rgba(99,102,241,0.3)",
              transform: `rotate(${spinAngle}deg)`,
            }}
          />
        )}
      </div>
    </div>
  );
};

export const S17_RunningToolStack: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Block entrance: slides up from below with fade
  const blockProgress = spring({ frame, fps, config: { damping: 25 } });
  const blockY = interpolate(blockProgress, [0, 1], [30, 0]);
  const blockOpacity = interpolate(blockProgress, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });

  // "Used 6 tools" label fades in after last icon
  const labelProgress = spring({
    frame: frame - (STAGGER_STEP * 5 + 5),
    fps,
    config: { damping: 200 },
  });
  const labelOpacity = interpolate(labelProgress, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });

  // Accordion springs open at ACCORDION_START with bouncy physics
  const accordionProgress = spring({
    frame: frame - ACCORDION_START,
    fps,
    config: { damping: 10, stiffness: 90 },
  });

  return (
    <AbsoluteFill>
      {/* Stacked icon entries */}
      {TOOL_CALLS.map((_, i) => (
        <Sequence key={i} from={i * STAGGER_STEP}>
          <Audio src={SFX.uiSwitch} volume={0.18} />
        </Sequence>
      ))}
      {/* Accordion springs open */}
      <Sequence from={ACCORDION_START}><Audio src={SFX.whoosh} volume={0.3} /></Sequence>
      {/* Tool rows cascade in */}
      {TOOL_CALLS.map((_, i) => (
        <Sequence key={`row-${i}`} from={ACCORDION_START + i * 6}>
          <Audio src={SFX.uiSwitch} volume={0.22} />
        </Sequence>
      ))}
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
        <div
          style={{
            width: 700,
            display: "flex",
            flexDirection: "column",
            gap: 28,
            transform: "scale(1.0)",
            transformOrigin: "center center",
          }}
        >
          {/* WorkflowVideoCard */}
          <WorkflowVideoCard
            title="Daily Morning Briefing"
            schedule="Every day at 8:00 AM"
            status="running"
          />

          {/* Accordion block */}
          <div
            style={{
              width: 700,
              background: "#18181b",
              borderRadius: 24,
              padding: "24px 32px",
              overflow: "hidden",
              transform: `translateY(${blockY}px)`,
              opacity: blockOpacity,
              maxHeight: `${120 + accordionProgress * 700}px`,
            }}
          >
            {/* Header row */}
            <div
              style={{
                display: "flex",
                alignItems: "center",
                marginBottom: accordionProgress > 0.05 ? 24 : 0,
              }}
            >
              {/* Stacked tool icons */}
              <div style={{ display: "flex", alignItems: "center" }}>
                {TOOL_CALLS.map((tool, i) => {
                  const iconProgress = spring({
                    frame: frame - i * STAGGER_STEP,
                    fps,
                    config: { damping: 200 },
                  });
                  const scale = interpolate(
                    iconProgress,
                    [0, 0.7, 1],
                    [0, 1.15, 1.0]
                  );

                  return (
                    <div
                      key={i}
                      style={{
                        width: 48,
                        height: 48,
                        borderRadius: 12,
                        background: "#27272a",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        overflow: "hidden",
                        transform: `rotate(${ROTATIONS[i]}deg) scale(${scale})`,
                        zIndex: TOOL_CALLS.length - i,
                        position: "relative",
                        marginLeft: i > 0 ? -10 : 0,
                        flexShrink: 0,
                      }}
                    >
                      <Img
                        src={staticFile(tool.icon)}
                        style={{
                          width: 32,
                          height: 32,
                          objectFit: "contain",
                          filter: tool.icon.includes("github")
                            ? "invert(1)"
                            : undefined,
                        }}
                      />
                    </div>
                  );
                })}
              </div>

              {/* "Used 6 tools" label */}
              <span
                style={{
                  color: "#a1a1aa",
                  fontFamily: FONTS.body,
                  fontSize: 26,
                  fontWeight: 500,
                  marginLeft: 10,
                  opacity: labelOpacity,
                  flexShrink: 0,
                }}
              >
                Used 6 tools
              </span>

              {/* Chevron */}
              <span
                style={{
                  marginLeft: "auto",
                  color: COLORS.zinc500,
                  fontSize: 26,
                  fontFamily: FONTS.body,
                  lineHeight: 1,
                }}
              >
                ›
              </span>
            </div>

            {/* Tool rows */}
            <div style={{ display: "flex", flexDirection: "column" }}>
              {TOOL_CALLS.map((tool, i) => (
                <ToolRow
                  key={i}
                  tool={tool}
                  index={i}
                  accordionProgress={accordionProgress}
                  isLast={i === TOOL_CALLS.length - 1}
                />
              ))}
            </div>
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};
