import { FlashIcon } from "@theexperiencecompany/gaia-icons/solid-rounded";
import type React from "react";
import {
  AbsoluteFill,
  Audio,
  Img,
  Sequence,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { COLORS, FONTS } from "../constants";
import { SFX } from "../sfx";

// Triggers backed by real backend integration events (apps/api/app/models/trigger_configs.py)
// Icons must exist in apps/video/public/images/icons/
const TRIGGERS = [
  {
    icon: "images/icons/gmail.svg",
    label: "On new email",
    integration: "Gmail",
    invert: false,
  },
  {
    icon: "images/icons/github.svg",
    label: "On pull request",
    integration: "GitHub",
    invert: true,
  },
  {
    icon: "images/icons/slack.svg",
    label: "On new message",
    integration: "Slack",
    invert: false,
  },
  {
    icon: "images/icons/googlecalendar.webp",
    label: "On calendar event",
    integration: "Google Calendar",
    invert: false,
  },
  {
    icon: "images/icons/notion.webp",
    label: "On new page",
    integration: "Notion",
    invert: false,
  },
  {
    icon: "images/icons/asana.svg",
    label: "On task update",
    integration: "Asana",
    invert: false,
  },
  {
    icon: "images/icons/todoist.svg",
    label: "On new task",
    integration: "Todoist",
    invert: false,
  },
  {
    icon: "images/icons/googlesheets.webp",
    label: "On new row",
    integration: "Google Sheets",
    invert: false,
  },
];

// 8 items → 7 transitions, firing every 16 frames for a tight slot-machine click feel
const TRANSITION_STARTS = [16, 32, 48, 64, 80, 96, 112];

const ITEM_H = 240;
// Tall viewport — sub-headline removed so slot gets more vertical room
const VIEWPORT_H = 800;

export const S22c_TriggerSlots: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Headline entrance
  const headlineP = spring({ frame, fps, config: { damping: 200 } });
  const headlineOpacity = interpolate(headlineP, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });
  const headlineY = interpolate(headlineP, [0, 1], [-20, 0]);

  // Slot machine: spring summation — each spring fires and scrolls one item
  const scrollY = TRANSITION_STARTS.reduce((acc, startFrame) => {
    const p = spring({
      frame: frame - startFrame,
      fps,
      config: { damping: 12, stiffness: 160 },
    });
    return acc - interpolate(p, [0, 1], [0, ITEM_H]);
  }, 0);

  // Active item index (for dot indicator)
  const activeIndex = Math.min(
    TRIGGERS.length - 1,
    Math.max(0, Math.round(-scrollY / ITEM_H)),
  );

  return (
    <AbsoluteFill
      style={{
        background: COLORS.bgLight,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "flex-start",
        padding: "72px 200px 0",
      }}
    >
      {/* Slot machine click for each scroll step */}
      {TRANSITION_STARTS.map((f) => (
        <Sequence key={f} from={f}>
          <Audio src={SFX.uiSwitch} volume={0.4} />
        </Sequence>
      ))}
      {/* Headline row — single line, full available width */}
      <div
        style={{
          width: "100%",
          display: "flex",
          alignItems: "center",
          gap: 24,
          position: "relative",
          top: "100px",
          opacity: headlineOpacity,
          transform: `translateY(${headlineY}px)`,
          whiteSpace: "nowrap",
        }}
      >
        <div
          style={{
            width: 60,
            height: 60,
            borderRadius: 16,
            background: "rgba(245,158,11,0.12)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            flexShrink: 0,
          }}
        >
          <FlashIcon size={34} style={{ color: "#f59e0b" }} />
        </div>
        <div
          style={{
            fontFamily: FONTS.display,
            fontSize: 96,
            fontWeight: 700,
            color: COLORS.textDark,
            lineHeight: 1.0,
            textTransform: "uppercase" as const,
            whiteSpace: "nowrap",
          }}
        >
          Triggered by anything.
        </div>
      </div>

      {/* Slot machine */}
      <div
        style={{
          width: "100%",
          position: "relative",
          height: VIEWPORT_H,
          overflow: "hidden",
          borderRadius: 24,
        }}
      >
        {/* Selection box: amber lines marking the center slot */}
        <div
          style={{
            position: "absolute",
            top: "50%",
            left: 0,
            right: 0,
            height: ITEM_H,
            transform: "translateY(-50%)",
            borderTop: "2px solid #00bbff",
            borderBottom: "2px solid #00bbff",
            background: "#00bbff10",
            pointerEvents: "none",
            zIndex: 5,
          }}
        />

        {/* Gradient mask — top */}
        {/* <div
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            right: 0,
            height: 100,
            background: "linear-gradient(to bottom, #18181b, transparent)",
            zIndex: 10,
            pointerEvents: "none",
          }}
        /> */}

        {/* Gradient mask — bottom */}
        {/* <div
          style={{
            position: "absolute",
            bottom: 0,
            left: 0,
            right: 0,
            height: 100,
            background: "linear-gradient(to top, #18181b, transparent)",
            zIndex: 10,
            pointerEvents: "none",
          }}
        /> */}

        {/* Scrolling items strip */}
        <div
          style={{
            transform: `translateY(${scrollY + (VIEWPORT_H - ITEM_H) / 2}px)`,
          }}
        >
          {TRIGGERS.map((trigger, i) => {
            // Distance from viewport center in item-units (0 = active, 1 = one slot away)
            const dist = Math.abs(scrollY + i * ITEM_H);
            const normalizedDist = dist / ITEM_H;
            // Inactive items: near-invisible and heavily blurred
            const itemOpacity = Math.max(0.05, 1 - normalizedDist * 0.95);
            const blurPx = Math.min(22, normalizedDist * 14);
            const itemScale = Math.max(0.88, 1 - normalizedDist * 0.08);

            return (
              <div
                key={i}
                style={{
                  height: ITEM_H,
                  display: "flex",
                  alignItems: "center",
                  gap: 40,
                  padding: "0 56px",
                  opacity: itemOpacity,
                  filter: blurPx > 0.5 ? `blur(${blurPx}px)` : undefined,
                  transform: `scale(${itemScale})`,
                  transformOrigin: "center center",
                }}
              >
                {/* Integration icon */}
                <div
                  style={{
                    width: 108,
                    height: 108,
                    borderRadius: 26,
                    background: "#27272a",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    flexShrink: 0,
                    overflow: "hidden",
                  }}
                >
                  <Img
                    src={staticFile(trigger.icon)}
                    style={{
                      width: 68,
                      height: 68,
                      objectFit: "contain",
                      filter: trigger.invert ? "invert(1)" : undefined,
                    }}
                  />
                </div>

                {/* Text */}
                <div style={{ flex: 1 }}>
                  <div
                    style={{
                      fontFamily: FONTS.body,
                      fontSize: 24,
                      color: "#00bbff",
                      fontWeight: 500,
                      marginBottom: 15,
                      textTransform: "uppercase" as const,
                      letterSpacing: 1,
                    }}
                  >
                    {trigger.integration}
                  </div>
                  <div
                    style={{
                      fontFamily: FONTS.display,
                      fontSize: 60,
                      fontWeight: 700,
                      color: "#f4f4f5",
                      lineHeight: 1.05,
                      textTransform: "uppercase" as const,
                    }}
                  >
                    {trigger.label}
                  </div>
                </div>

                {/* Active indicator dot */}
                <div
                  style={{
                    width: 14,
                    height: 14,
                    borderRadius: "50%",
                    background: "#f59e0b",
                    flexShrink: 0,
                    opacity: i === activeIndex ? 1 : 0,
                    transition: "opacity 0.1s",
                  }}
                />
              </div>
            );
          })}
        </div>
      </div>
    </AbsoluteFill>
  );
};
