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
import { SlackMessageCard } from "../components/SlackMessageCard";

export const S07_SlackNotify: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const slackP = spring({
    frame: frame - 35,
    fps,
    config: { damping: 22, stiffness: 100 },
  });
  const slackOpacity = interpolate(slackP, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });
  const slackY = interpolate(slackP, [0, 1], [30, 0]);

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
      <Sequence from={35}>
        <Audio src={SFX.uiSwitch} volume={0.25} />
      </Sequence>

      <ChatThread
        messages={[
          {
            message: "Slacked your co-founder.",
            timestamp: "5:00 AM",
            delay: 8,
          },
        ]}
      />

      <div
        style={{
          transform: `translateY(${slackY}px)`,
          opacity: slackOpacity,
        }}
      >
        <SlackMessageCard
          workspace="Company"
          channel="founders"
          from="GAIA"
          message="Heads up — Sequoia replied. Meeting likely this week. Deck updated, data room clean, prep doc ready."
          enterDelay={30}
        />
      </div>
    </AbsoluteFill>
  );
};
