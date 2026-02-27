import React from "react";
import { useCurrentFrame } from "remotion";
import { COLORS } from "../constants";

interface TypingTextProps {
  text: string;
  framesPerChar?: number; // default 1
  delay?: number;
  cursorColor?: string;
  showCursor?: boolean;
  style?: React.CSSProperties;
}

export const TypingText: React.FC<TypingTextProps> = ({
  text,
  framesPerChar = 1,
  delay = 0,
  cursorColor = COLORS.primary,
  showCursor = true,
  style,
}) => {
  const frame = useCurrentFrame();
  const charIndex = Math.min(
    Math.floor(Math.max(0, frame - delay) / framesPerChar),
    text.length,
  );
  const displayText = text.slice(0, charIndex);
  const hasCursor = showCursor && frame >= delay;

  // Cursor blink: every 15 frames
  const cursorOpacity =
    hasCursor ? (Math.floor((frame - delay) / 15) % 2 === 0 ? 1 : 0) : 0;

  return (
    <span style={style}>
      {displayText}
      <span
        style={{
          display: "inline-block",
          width: 2,
          height: "1.1em",
          backgroundColor: cursorColor,
          marginLeft: 2,
          verticalAlign: "text-bottom",
          opacity: cursorOpacity,
        }}
      />
    </span>
  );
};
