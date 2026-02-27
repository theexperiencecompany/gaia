import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig, spring, interpolate, Img, staticFile } from "remotion";
import { InboxUnreadIcon, CalendarUpload01Icon, CheckmarkCircle02Icon, Target02Icon, ZapIcon } from "@theexperiencecompany/gaia-icons/solid-rounded";
import { COLORS, FONTS } from "../constants";

interface ChipProps {
  label: string;
  color: string;
  iconNode: React.ReactNode;
  delay: number;
}

const Chip: React.FC<ChipProps> = ({ label, color, iconNode, delay }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = spring({ frame: frame - delay, fps, config: { damping: 12, stiffness: 200 } });
  const scale = interpolate(p, [0, 0.5, 1], [0, 1.1, 1.0]);
  const opacity = interpolate(p, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 10,
      padding: "10px 28px", borderRadius: 40,
      background: color + "18",
      transform: `scale(${scale})`, opacity,
    }}>
      {iconNode}
      <span style={{ fontFamily: FONTS.body, fontSize: 26, fontWeight: 500, color: COLORS.textDark }}>{label}</span>
    </div>
  );
};

export const S29_OneDashboard: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const chips = [
    { label: "Emails", color: "#38bdf8", iconNode: <InboxUnreadIcon size={28} style={{ color: "#38bdf8" }} />, delay: 50 },
    { label: "Calendar", color: "#60a5fa", iconNode: <CalendarUpload01Icon size={28} style={{ color: "#60a5fa" }} />, delay: 60 },
    { label: "Todos", color: "#34d399", iconNode: <CheckmarkCircle02Icon size={28} style={{ color: "#34d399" }} />, delay: 70 },
    { label: "Goals", color: "#6366f1", iconNode: <Target02Icon size={28} style={{ color: "#6366f1" }} />, delay: 80 },
    { label: "Workflows", color: "#f59e0b", iconNode: <ZapIcon size={28} style={{ color: "#f59e0b" }} />, delay: 90 },
  ];

  // Line 1: "One dashboard."
  const words1 = ["One", "dashboard."];
  const line1Chars = words1.map((_, i) => {
    const prog = spring({ frame: frame - i * 5, fps, config: { damping: 18, stiffness: 120 } });
    return {
      y: interpolate(prog, [0, 1], [40, 0]),
      opacity: interpolate(prog, [0, 0.1], [0, 1], { extrapolateRight: "clamp" }),
    };
  });

  // Line 2: "Everything." (cyan) — 15 frames later
  const line2Progress = spring({ frame: frame - 15, fps, config: { damping: 18, stiffness: 120 } });
  const line2Scale = interpolate(line2Progress, [0, 1], [0.9, 1.0]);
  const line2Opacity = interpolate(line2Progress, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });
  const line2Y = interpolate(line2Progress, [0, 1], [40, 0]);

  // Breathing
  const breathe = interpolate(Math.sin((frame / 80) * Math.PI * 2), [-1, 1], [1.0, 1.008]);

  return (
    <AbsoluteFill style={{ background: COLORS.bgLight }}>
      {/* Typography */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          gap: 8,
          transform: `scale(${breathe})`,
        }}
      >
        {/* Line 1 */}
        <div style={{ display: "flex", gap: 32 }}>
          {words1.map((word, i) => (
            <span
              key={i}
              style={{
                display: "inline-block",
                fontFamily: FONTS.display,
                fontSize: 200,
                fontWeight: 800,
                color: COLORS.textDark,
                lineHeight: 1.0,
                letterSpacing: "0",
                transform: `translateY(${line1Chars[i].y}px)`,
                opacity: line1Chars[i].opacity,
              }}
            >
              {word}
            </span>
          ))}
        </div>

        {/* Line 2: "Everything." in cyan */}
        <div
          style={{
            fontFamily: FONTS.display,
            fontSize: 200,
            fontWeight: 800,
            color: COLORS.primary,
            lineHeight: 1.0,
            letterSpacing: "0",
            transform: `translateY(${line2Y}px) scale(${line2Scale})`,
            opacity: line2Opacity,
          }}
        >
          Everything.
        </div>

        {/* Chip row */}
        <div style={{ display: "flex", gap: 14, marginTop: 48 }}>
          {chips.map((chip, i) => <Chip key={i} label={chip.label} color={chip.color} iconNode={chip.iconNode} delay={chip.delay} />)}
        </div>
      </div>
    </AbsoluteFill>
  );
};
