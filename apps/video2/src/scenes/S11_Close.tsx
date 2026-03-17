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
import { TypingText } from "../components/TypingText";

interface WordBeatProps {
  text: string;
  startFrame: number;
  exitFrame: number;
  color: string;
}

const WordBeat: React.FC<WordBeatProps> = ({
  text,
  startFrame,
  exitFrame,
  color,
}) => {
  const frame = useCurrentFrame();
  if (frame < startFrame || frame >= exitFrame) return null;

  const elapsed = frame - startFrame;
  const punchT = Math.min(1, elapsed / 4);
  const scale = interpolate(punchT, [0, 0.5, 1], [1.05, 1.01, 1.0]);

  return (
    <div
      style={{
        fontFamily: FONTS.display,
        fontSize: 96,
        fontWeight: 800,
        color,
        textTransform: "uppercase",
        textAlign: "center",
        letterSpacing: "-0.03em",
        lineHeight: 1,
        transform: `scale(${scale})`,
      }}
    >
      {text}
    </div>
  );
};

export const S11_Close: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const ctaP = spring({
    frame: frame - 210,
    fps,
    config: { damping: 200 },
  });
  const ctaOpacity = interpolate(ctaP, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });

  const radialOpacity = interpolate(frame, [0, 20], [0, 1], {
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill
      style={{
        background: COLORS.bgLight,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 20,
      }}
    >
      {/* Radial bloom */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          background: `radial-gradient(ellipse at 50% 55%, ${COLORS.primary}14 0%, transparent 45%)`,
          opacity: radialOpacity,
          pointerEvents: "none",
        }}
      />

      {/* SFX */}
      <Sequence from={0}>
        <Audio src={SFX.whip} volume={0.55} />
      </Sequence>
      <Sequence from={60}>
        <Audio src={SFX.whip} volume={0.5} />
      </Sequence>
      <Sequence from={120}>
        <Audio src={SFX.whip} volume={0.45} />
      </Sequence>

      {/* Word beats */}
      <WordBeat
        text="They replied at midnight."
        startFrame={0}
        exitFrame={60}
        color={COLORS.textDark}
      />
      <WordBeat
        text="You replied at 7am"
        startFrame={60}
        exitFrame={120}
        color={COLORS.textDark}
      />
      <WordBeat
        text="with everything."
        startFrame={120}
        exitFrame={9999}
        color={COLORS.primary}
      />

      {/* CTA */}
      {frame >= 210 && (
        <div
          style={{
            opacity: ctaOpacity,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            gap: 24,
            marginTop: 40,
          }}
        >
          <div
            style={{
              fontFamily: FONTS.display,
              fontSize: 52,
              fontWeight: 700,
              textTransform: "uppercase",
              letterSpacing: "-0.02em",
              color: COLORS.textDark,
            }}
          >
            GAIA
          </div>

          {/* Search bar pill */}
          <div
            style={{
              background: COLORS.surface,
              borderRadius: 999,
              padding: "18px 40px",
              minWidth: 340,
              textAlign: "center",
            }}
          >
            <TypingText
              text="heygaia.io"
              framesPerChar={3}
              delay={220}
              cursorColor={COLORS.primary}
              style={{
                fontFamily: FONTS.body,
                fontSize: 30,
                color: COLORS.textDark,
              }}
            />
          </div>
        </div>
      )}
    </AbsoluteFill>
  );
};
