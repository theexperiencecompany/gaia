import React from "react";
import { useCurrentFrame, useVideoConfig, spring, interpolate, Img, staticFile } from "remotion";
import { FONTS } from "../constants";

interface PlatformIconProps {
  src: string;
  label: string;
  delay: number;
  size?: number;
  iconIndex?: number;
  comingSoon?: boolean;
  opacity?: number;
  textColor?: string;
}

export const PlatformIcon: React.FC<PlatformIconProps> = ({
  src,
  label,
  delay,
  size = 120,
  iconIndex = 0,
  comingSoon = false,
  opacity: baseopacity = 1,
  textColor = "white",
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const bounceProgress = spring({
    frame: frame - delay,
    fps,
    config: { damping: 8, stiffness: 180, mass: 0.8 },
  });

  const scale = interpolate(bounceProgress, [0, 1], [0, 1]);
  const y = interpolate(bounceProgress, [0, 1], [60, 0]);

  // Perpetual hover float after settling
  const floatY =
    bounceProgress > 0.95
      ? Math.sin(((frame / 30) * Math.PI * 2 + iconIndex) % (Math.PI * 2)) * 5
      : 0;

  const finalOpacity = comingSoon
    ? baseopacity * 0.65 * interpolate(bounceProgress, [0, 0.2], [0, 1], { extrapolateRight: "clamp" })
    : baseopacity * interpolate(bounceProgress, [0, 0.2], [0, 1], { extrapolateRight: "clamp" });

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: 12,
        transform: `translateY(${y + floatY}px) scale(${scale})`,
        opacity: finalOpacity,
        position: "relative",
      }}
    >
      <Img
        src={staticFile(src)}
        style={{
          width: size,
          height: size,
          borderRadius: size * 0.22,
          display: "block",
        }}
      />
      <span
        style={{
          fontFamily: FONTS.body,
          fontWeight: 600,
          fontSize: 18,
          color: textColor,
          opacity: interpolate(bounceProgress, [0.5, 1], [0, 1], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
          }),
        }}
      >
        {label}
      </span>
      {comingSoon && (
        <div
          style={{
            position: "absolute",
            bottom: 22,
            left: "50%",
            transform: "translateX(-50%)",
            background: "#3f3f46",
            color: "#a1a1aa",
            fontSize: 11,
            fontFamily: FONTS.body,
            fontWeight: 600,
            padding: "3px 8px",
            borderRadius: 6,
            whiteSpace: "nowrap",
          }}
        >
          Coming Soon
        </div>
      )}
    </div>
  );
};
