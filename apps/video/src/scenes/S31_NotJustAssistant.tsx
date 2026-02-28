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

const WORDS = ["does the", "boring stuff."];

export const S31_NotJustAssistant: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // GAIA title slams up from below with a bouncy spring
  const gaiaSpring = spring({
    frame,
    fps,
    config: { damping: 200 },
  });
  const gaiaY = interpolate(gaiaSpring, [0, 1], [60, 0]);

  return (
    <AbsoluteFill
      style={{
        background: COLORS.bgLight,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 32,
        overflow: "hidden",
      }}
    >
      {/* GAIA slam */}
      <Sequence from={0}><Audio src={SFX.whoosh} volume={0.45} /></Sequence>
      {/* "handles everything." word beats */}
      {WORDS.map((_, i) => (
        <Sequence key={i} from={8 + i * 3}>
          <Audio src={SFX.uiSwitch} volume={0.28} />
        </Sequence>
      ))}
      {/* GAIA title */}
      <div
        style={{
          fontFamily: FONTS.display,
          textTransform: "uppercase" as const,
          fontSize: 280,
          fontWeight: 700,
          color: COLORS.textDark,
          letterSpacing: "-0.03em",
          lineHeight: 1,
          transform: `translateY(${gaiaY}px)`,
        }}
      >
        GAIA
      </div>

      {/* Staggered word row */}
      <div
        style={{
          display: "flex",
          flexDirection: "row",
          alignItems: "baseline",
          gap: 24,
          overflow: "hidden",
        }}
      >
        {WORDS.map((word, i) => {
          const wordFrame = frame - (8 + i * 3);
          const wordSpring = spring({
            frame: wordFrame,
            fps,
            config: { damping: 200 },
          });
          const wordY = interpolate(wordSpring, [0, 1], [24, 0]);
          const wordOpacity = interpolate(wordSpring, [0, 0.15], [0, 1], {
            extrapolateRight: "clamp",
          });

          return (
            <div
              key={word}
              style={{
                fontFamily: FONTS.body,
                fontSize: 96,
                fontWeight: 500,
                color: COLORS.zinc600,
                transform: `translateY(${wordY}px)`,
                opacity: wordOpacity,
              }}
            >
              {word}
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
