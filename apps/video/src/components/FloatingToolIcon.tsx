import React from "react";
import { useCurrentFrame, useVideoConfig, spring, interpolate, Img, staticFile } from "remotion";

interface FloatingToolIconProps {
  src: string;
  alt: string;
  x: number;
  y: number;
  rotation: number;
  size: number;
  delay: number;
  floatPhase: number; // 0–2π offset for float animation
}

export const FloatingToolIcon: React.FC<FloatingToolIconProps> = ({
  src,
  alt,
  x,
  y,
  rotation,
  size,
  delay,
  floatPhase,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const progress = spring({
    frame: frame - delay,
    fps,
    config: { damping: 12, stiffness: 60 },
  });

  // Fly in from beyond the final position
  const startX = x * 2.5;
  const startY = y * 2.5;
  const currentX = interpolate(progress, [0, 1], [startX, x]);
  const currentY = interpolate(progress, [0, 1], [startY, y]);

  // Perpetual float after settling
  const floatOffset =
    Math.sin(((frame / 60) * Math.PI * 2 + floatPhase) % (Math.PI * 2)) * 6;
  const finalY = currentY + (progress > 0.9 ? floatOffset : 0);

  return (
    <div
      style={{
        position: "absolute",
        left: "50%",
        top: "50%",
        transform: `translate(${currentX - size / 2}px, ${finalY - size / 2}px) rotate(${rotation}deg)`,
        opacity: interpolate(progress, [0, 0.15], [0, 1], {
          extrapolateRight: "clamp",
        }),
        width: size,
        height: size,
      }}
    >
      <Img
        src={staticFile(src)}
        style={{
          width: "100%",
          height: "100%",
          borderRadius: size * 0.2,
          display: "block",
        }}
      />
    </div>
  );
};
