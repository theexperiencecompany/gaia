import type React from "react";

interface CardOverlayProps {
  overlayColor?: string;
  overlayOpacity?: number;
}

export const CardOverlay: React.FC<CardOverlayProps> = ({
  overlayColor,
  overlayOpacity = 40,
}) => {
  if (!overlayColor) return null;

  return (
    <div
      className="pointer-events-none absolute inset-0 z-3"
      style={{
        background: overlayColor,
        mixBlendMode: "overlay",
        opacity: overlayOpacity / 100,
      }}
    />
  );
};
