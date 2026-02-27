import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig, spring, interpolate, Img, staticFile } from "remotion";
import { COLORS, FONTS } from "../constants";

const PILLARS = [
  { iconSrc: "images/icons/gmail.svg",           label: "Gmail",    accent: "#EA4335" },
  { iconSrc: "images/icons/googlecalendar.webp", label: "Calendar", accent: COLORS.primary },
  { iconSrc: "images/icons/notion.webp",         label: "Todos",    accent: "#22c55e" },
  { iconSrc: "images/icons/asana.svg",           label: "Goals",    accent: "#a855f7" },
];

interface PillarIconProps {
  pillar: (typeof PILLARS)[number];
  index: number;
}

const PillarIcon: React.FC<PillarIconProps> = ({ pillar, index }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const delay = index * 12;
  const progress = spring({
    frame: frame - delay,
    fps,
    config: { damping: 10, stiffness: 150 },
  });

  const scale = interpolate(progress, [0, 0.5, 1], [0, 1.1, 1.0]);
  const y = interpolate(progress, [0, 1], [20, 0]);
  const opacity = interpolate(progress, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });

  // Label delay
  const labelProgress = spring({ frame: frame - delay - 8, fps, config: { damping: 200 } });
  const labelOpacity = interpolate(labelProgress, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });

  // Float
  const floatY = Math.sin(((frame / 30) * Math.PI * 2 + index) % (Math.PI * 2)) * 5;

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: 16,
        transform: `scale(${scale}) translateY(${y + (progress > 0.95 ? floatY : 0)}px)`,
        opacity,
      }}
    >
      <div
        style={{
          width: 96,
          height: 96,
          borderRadius: 24,
          background: pillar.accent + "22",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <Img src={staticFile(pillar.iconSrc)} style={{ width: 56, height: 56, objectFit: "contain" }} />
      </div>
      <span
        style={{
          fontFamily: FONTS.body,
          fontSize: 22,
          fontWeight: 600,
          color: COLORS.textDark,
          opacity: labelOpacity,
        }}
      >
        {pillar.label}
      </span>
    </div>
  );
};

export const S30_FourPillars: React.FC = () => {
  return (
    <AbsoluteFill
      style={{
        background: COLORS.bgLight,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "flex-start",
          gap: 120,
        }}
      >
        {PILLARS.map((pillar, i) => (
          <PillarIcon key={i} pillar={pillar} index={i} />
        ))}
      </div>
    </AbsoluteFill>
  );
};
