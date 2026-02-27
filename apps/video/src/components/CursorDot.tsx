import React from "react";
import { useCurrentFrame, useVideoConfig, spring, interpolate } from "remotion";

interface Waypoint {
  x: number;
  y: number;
  frame: number;
}

interface CursorDotProps {
  positions: Waypoint[];
  size?: number;
  color?: string;
  clickFrame?: number; // Frame at which to show click animation
}

export const CursorDot: React.FC<CursorDotProps> = ({
  positions,
  size = 20,
  color = "rgba(255,255,255,0.9)",
  clickFrame,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  if (positions.length === 0) return null;

  // Find current segment
  let currentX = positions[0].x;
  let currentY = positions[0].y;

  for (let i = 0; i < positions.length - 1; i++) {
    const from = positions[i];
    const to = positions[i + 1];
    if (frame >= from.frame && frame <= to.frame) {
      const segmentProgress = spring({
        frame: frame - from.frame,
        fps,
        config: { damping: 15, stiffness: 100 },
      });
      currentX = interpolate(segmentProgress, [0, 1], [from.x, to.x]);
      currentY = interpolate(segmentProgress, [0, 1], [from.y, to.y]);
      break;
    } else if (frame > to.frame) {
      currentX = to.x;
      currentY = to.y;
    }
  }

  // Click scale animation
  const clickScale =
    clickFrame !== undefined
      ? spring({
          frame: frame - clickFrame,
          fps,
          config: { damping: 30, stiffness: 400 },
          durationInFrames: 15,
        })
      : 0;

  const scale =
    clickFrame !== undefined && frame >= clickFrame
      ? interpolate(clickScale, [0, 0.5, 1], [1, 0.8, 1])
      : 1;

  return (
    <div
      style={{
        position: "absolute",
        width: size,
        height: size,
        borderRadius: "50%",
        background: color,
        boxShadow:
          "0 0 0 3px rgba(255,255,255,0.2), 0 2px 8px rgba(0,0,0,0.4)",
        pointerEvents: "none",
        zIndex: 9999,
        transform: `translate(${currentX - size / 2}px, ${currentY - size / 2}px) scale(${scale})`,
      }}
    />
  );
};
