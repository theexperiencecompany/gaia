import React from "react";
import { AbsoluteFill, Img, staticFile } from "remotion";
import { COLORS } from "../constants";

interface SceneBackgroundProps {
  variant?: "solid" | "mesh" | "light";
  meshOpacity?: number;
}

export const SceneBackground: React.FC<SceneBackgroundProps> = ({
  variant = "solid",
  meshOpacity = 0.12,
}) => (
  <AbsoluteFill style={{ background: variant === "light" ? COLORS.bgLight : COLORS.bg }}>
    {variant === "mesh" && (
      <Img
        src={staticFile("images/wallpapers/mesh_gradient_1.webp")}
        style={{
          position: "absolute",
          inset: 0,
          width: "100%",
          height: "100%",
          objectFit: "cover",
          opacity: meshOpacity,
        }}
      />
    )}
  </AbsoluteFill>
);
