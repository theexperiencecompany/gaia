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
import { COLORS } from "../constants";
import { SFX } from "../sfx";
import { ChatThread } from "../components/ChatThread";
import { DeckSlidesCard } from "../components/DeckSlidesCard";

export const S04_DeckUpdated: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const scaleP = spring({
    frame: frame - 40,
    fps,
    config: { damping: 22, stiffness: 100 },
  });
  const cardScale = interpolate(scaleP, [0, 1], [1, 1.08]);

  return (
    <AbsoluteFill
      style={{
        background: COLORS.bgLight,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 36,
      }}
    >
      {/* SFX */}
      <Sequence from={8}>
        <Audio src={SFX.whoosh} volume={0.25} />
      </Sequence>
      <Sequence from={40}>
        <Audio src={SFX.uiSwitch} volume={0.25} />
      </Sequence>
      <Sequence from={80}>
        <Audio src={SFX.whip} volume={0.5} />
      </Sequence>

      <ChatThread
        messages={[
          {
            message:
              "Updated your deck. Metrics current, narrative tailored to her thesis.",
            timestamp: "12:20 AM",
            delay: 8,
          },
        ]}
      />

      <div style={{ transform: `scale(${cardScale})` }}>
        <DeckSlidesCard
          enterDelay={30}
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
      </div>
    </AbsoluteFill>
  );
};
