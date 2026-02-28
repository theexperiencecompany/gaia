import type React from "react";
import {
  AbsoluteFill,
  Audio,
  Sequence,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { COLORS, FONTS } from "../constants";
import { SFX } from "../sfx";

interface WordToken {
  text: string;
  color: string;
}

interface AnimatedWordProps {
  token: WordToken;
  globalIndex: number;
  startOffset: number;
}

const AnimatedWord: React.FC<AnimatedWordProps> = ({
  token,
  globalIndex,
  startOffset,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const p = spring({
    frame: frame - (startOffset + globalIndex * 3),
    fps,
    config: { damping: 200 },
  });

  const opacity = interpolate(p, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });
  const translateY = interpolate(p, [0, 1], [20, 0]);

  return (
    <span
      style={{
        display: "inline-block",
        marginRight: "0.25em",
        color: token.color,
        opacity,
        transform: `translateY(${translateY}px)`,
      }}
    >
      {token.text}
    </span>
  );
};

const LINE_1_TOKENS: WordToken[] = [
  { text: "Your digital life,", color: "#fafafa" },
  { text: "connected.", color: "#00bbff" },
];

const LINE_2_TOKENS: WordToken[] = [
  { text: "Built", color: "#71717a" },
  { text: "by", color: "#71717a" },
  { text: "thousands.", color: "#71717a" },
  { text: "Used", color: "#71717a" },
  { text: "by", color: "#71717a" },
  { text: "more.", color: "#71717a" },
];

const LINE_1_WORD_COUNT = LINE_1_TOKENS.length;
// LINE_1_WORD_COUNT words × 4 frames each + 8 frame gap between lines
const LINE_2_START_OFFSET = LINE_1_WORD_COUNT * 4 + 8;

export const S26d_IntegrationTagline: React.FC = () => {
  return (
    <AbsoluteFill
      style={{
        background: COLORS.bg,
        overflow: "hidden",
      }}
    >
      {/* Word beats */}
      {[0, 3, 16, 19, 22].map((f) => (
        <Sequence key={f} from={f}><Audio src={SFX.uiSwitch} volume={0.28} /></Sequence>
      ))}
      {/* Subtle cyan radial glow */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          background:
            "radial-gradient(ellipse 60% 50% at 50% 50%, rgba(0,187,255,0.06) 0%, transparent 70%)",
        }}
      />

      {/* Centered content */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          gap: 28,
          padding: "0 120px",
        }}
      >
        {/* Line 1 */}
        <div
          style={{
            fontFamily: FONTS.display,
            textTransform: "uppercase" as const,
            fontSize: 96,
            fontWeight: 700,
            lineHeight: 1.1,
            textAlign: "center",
          }}
        >
          {LINE_1_TOKENS.map((token, i) => (
            <AnimatedWord
              key={i}
              token={token}
              globalIndex={i}
              startOffset={0}
            />
          ))}
        </div>

        {/* Line 2 */}
        <div
          style={{
            fontFamily: FONTS.display,
            textTransform: "uppercase" as const,
            fontSize: 72,
            fontWeight: 700,
            lineHeight: 1.1,
            textAlign: "center",
          }}
        >
          {LINE_2_TOKENS.map((token, i) => (
            <AnimatedWord
              key={i}
              token={token}
              globalIndex={i}
              startOffset={LINE_2_START_OFFSET}
            />
          ))}
        </div>
      </div>
    </AbsoluteFill>
  );
};
