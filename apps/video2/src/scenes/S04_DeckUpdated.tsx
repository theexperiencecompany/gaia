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
import { DeckSlidesCard } from "../components/DeckSlidesCard";

export const S04_DeckUpdated: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const labelP = spring({
    frame: frame - 8,
    fps,
    config: { damping: 200 },
  });
  const labelOpacity = interpolate(labelP, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });
  const labelY = interpolate(labelP, [0, 1], [20, 0]);

  return (
    <AbsoluteFill
      style={{
        background: COLORS.bg,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 32,
      }}
    >
      <Sequence from={8}>
        <Audio src={SFX.whoosh} volume={0.2} />
      </Sequence>
      <Sequence from={60}>
        <Audio src={SFX.whip} volume={0.45} />
      </Sequence>

      <DeckSlidesCard
        enterDelay={8}
        slides={[
          { title: "Company Overview" },
          { title: "Market Opportunity" },
          {
            title: "Traction",
            highlight: true,
            metric: "$47K",
            metricLabel: "MRR · +18% MoM",
          },
          { title: "The Ask" },
        ]}
      />

      <div
        style={{
          opacity: labelOpacity,
          transform: `translateY(${labelY}px)`,
          fontFamily: FONTS.body,
          fontSize: 32,
          color: COLORS.zinc500,
        }}
      >
        Deck updated · narrative tailored to Sarah's thesis
      </div>
    </AbsoluteFill>
  );
};
