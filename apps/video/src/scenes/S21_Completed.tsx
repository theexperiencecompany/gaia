import type React from "react";
import {
  AbsoluteFill,
  Audio,
  interpolate,
  Sequence,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { SceneBackground } from "../components/SceneBackground";
import { COLORS, FONTS } from "../constants";
import { SFX } from "../sfx";

export const S21_Completed: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // "Delivered." slams in, holds, then gently fades for the next transition
  const doneProgress = spring({
    frame,
    fps,
    config: { damping: 18, stiffness: 100 },
  });
  const doneOpacity = interpolate(doneProgress, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });
  const doneScale = interpolate(doneProgress, [0, 0.5, 1], [0.85, 1.04, 1.0]);

  return (
    <AbsoluteFill>
      {/* "Delivered." slam */}
      <Sequence from={0}>
        <Audio src={SFX.whip} volume={0.7} />
      </Sequence>
      <SceneBackground variant="light" />
      <div
        style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <div
          style={{
            fontFamily: FONTS.display,
            textTransform: "uppercase" as const,
            fontSize: 200,
            fontWeight: 700,
            color: COLORS.textDark,
            opacity: doneOpacity,
            transform: `scale(${doneScale})`,
          }}
        >
          Delivered.
        </div>
      </div>
    </AbsoluteFill>
  );
};
