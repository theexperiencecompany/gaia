import React from "react";
import { useCurrentFrame, useVideoConfig, spring, interpolate } from "remotion";
import { COLORS, FONTS } from "../constants";

interface BigTextProps {
  text: string;
  font?: "editorial" | "inter";
  size?: number;
  italic?: boolean;
  color?: string;
  stagger?: number; // frames per word
  delay?: number;   // initial delay frames
  lineHeight?: number;
  letterSpacing?: string;
  maxWidth?: number;
  exitStartFrame?: number; // frame at which exit animation starts
  exitDuration?: number;   // frames for exit
}

export const BigText: React.FC<BigTextProps> = ({
  text,
  font = "editorial",
  size = 180,
  italic = false,
  color = COLORS.white,
  stagger = 4,
  delay = 0,
  lineHeight = 1.1,
  letterSpacing = "-0.02em",
  maxWidth = 1400,
  exitStartFrame,
  exitDuration = 20,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const words = text.split(" ");

  const exitOpacity =
    exitStartFrame !== undefined
      ? interpolate(frame, [exitStartFrame, exitStartFrame + exitDuration], [1, 0], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        })
      : 1;

  const exitY =
    exitStartFrame !== undefined
      ? interpolate(frame, [exitStartFrame, exitStartFrame + exitDuration], [0, -15], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        })
      : 0;

  return (
    <div
      style={{
        fontFamily: font === "editorial" ? FONTS.display : FONTS.body,
        textTransform: font === "editorial" ? ("uppercase" as const) : undefined,
        fontSize: size,
        fontStyle: italic ? "italic" : "normal",
        lineHeight,
        letterSpacing,
        color,
        textAlign: "center",
        display: "flex",
        flexWrap: "wrap",
        justifyContent: "center",
        gap: "0.25em",
        maxWidth,
        opacity: exitOpacity,
        transform: `translateY(${exitY}px)`,
      }}
    >
      {words.map((word, i) => {
        const wordFrame = frame - delay - i * stagger;
        const progress = spring({
          frame: wordFrame,
          fps,
          config: { damping: 18, stiffness: 120 },
        });
        return (
          <span
            key={i}
            style={{
              display: "inline-block",
              transform: `translateY(${interpolate(progress, [0, 1], [40, 0])}px)`,
              opacity: interpolate(progress, [0, 0.1], [0, 1], {
                extrapolateRight: "clamp",
              }),
            }}
          >
            {word}
          </span>
        );
      })}
    </div>
  );
};
