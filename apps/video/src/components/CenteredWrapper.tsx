import React from "react";

interface CenteredWrapperProps {
  scale?: number;
  translateX?: number;
  translateY?: number;
  children: React.ReactNode;
  style?: React.CSSProperties;
}

export const CenteredWrapper: React.FC<CenteredWrapperProps> = ({
  scale = 1,
  translateX = 0,
  translateY = 0,
  children,
  style,
}) => (
  <div
    style={{
      position: "absolute",
      inset: 0,
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      ...style,
    }}
  >
    <div
      style={{
        transform: `scale(${scale}) translate(${translateX}px, ${translateY}px)`,
        transformOrigin: "center center",
      }}
    >
      {children}
    </div>
  </div>
);
