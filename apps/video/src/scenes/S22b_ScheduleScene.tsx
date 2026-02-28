import { Clock01Icon } from "@theexperiencecompany/gaia-icons/solid-rounded";
import type React from "react";
import {
  AbsoluteFill,
  Audio,
  interpolate,
  Sequence,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { COLORS, FONTS } from "../constants";
import { SFX } from "../sfx";

const SCHEDULE_OPTIONS = [
  { label: "Every day at 8:00 AM", badge: "Daily" },
  { label: "Every Monday at 9:00 AM", badge: "Weekly" },
  { label: "Every hour", badge: "Hourly" },
  { label: "1st of every month", badge: "Monthly" },
  { label: "Custom cron expression", badge: "Advanced" },
];

export const S22b_ScheduleScene: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const headlineP = spring({ frame, fps, config: { damping: 200 } });
  const headlineOpacity = interpolate(headlineP, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });
  const headlineY = interpolate(headlineP, [0, 1], [-20, 0]);

  const subP = spring({ frame: frame - 6, fps, config: { damping: 200 } });
  const subOpacity = interpolate(subP, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill
      style={{
        background: COLORS.bgLight,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        padding: "0 120px",
      }}
    >
      {/* Headline beat */}
      {/* Row ticks — each schedule option pops in */}
      {SCHEDULE_OPTIONS.map((_, i) => (
        <Sequence key={i} from={18 + i * 9}>
          <Audio src={SFX.uiSwitch} volume={0.2} />
        </Sequence>
      ))}
      <div style={{ width: "100%" }}>
        {/* Icon + Headline — single line */}
        <div
          style={{
            opacity: headlineOpacity,
            transform: `translateY(${headlineY}px)`,
            marginBottom: 16,
            display: "flex",
            alignItems: "center",
            gap: 24,
            whiteSpace: "nowrap",
          }}
        >
          <div
            style={{
              width: 60,
              height: 60,
              borderRadius: 16,
              background: "rgba(96,165,250,0.12)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              flexShrink: 0,
            }}
          >
            <Clock01Icon size={34} style={{ color: "#60a5fa" }} />
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
            Runs on any schedule.
          </div>
        </div>

        {/* Sub-headline */}
        <div
          style={{
            fontFamily: FONTS.body,
            fontSize: 32,
            color: "#52525b",
            marginBottom: 48,
            marginLeft: 84,
            opacity: subOpacity,
          }}
        >
          Set it once. Run it forever.
        </div>

        {/* Schedule list card */}
        <div
          style={{
            background: "#18181b",
            borderRadius: 24,
            overflow: "hidden",
          }}
        >
          {SCHEDULE_OPTIONS.map((opt, i) => {
            const rowP = spring({
              frame: frame - (18 + i * 9),
              fps,
              config: { damping: 200 },
            });
            const rowOpacity = interpolate(rowP, [0, 0.1], [0, 1], {
              extrapolateRight: "clamp",
            });
            const rowY = interpolate(rowP, [0, 1], [18, 0]);

            return (
              <div
                key={i}
                style={{
                  opacity: rowOpacity,
                  transform: `translateY(${rowY}px)`,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  padding: "24px 32px",
                  borderTop:
                    i === 0 ? "none" : "1px solid rgba(255,255,255,0.05)",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
                  <div
                    style={{
                      width: 10,
                      height: 10,
                      borderRadius: "50%",
                      background: "#60a5fa",
                      flexShrink: 0,
                    }}
                  />
                  <span
                    style={{
                      fontFamily: FONTS.body,
                      fontSize: 36,
                      color: "#e4e4e7",
                      fontWeight: 400,
                    }}
                  >
                    {opt.label}
                  </span>
                </div>
                <span
                  style={{
                    fontFamily: FONTS.body,
                    fontSize: 26,
                    background: "rgba(96,165,250,0.1)",
                    padding: "6px 18px",
                    borderRadius: 8,
                    color: "#60a5fa",
                  }}
                >
                  {opt.badge}
                </span>
              </div>
            );
          })}
        </div>
      </div>
    </AbsoluteFill>
  );
};
