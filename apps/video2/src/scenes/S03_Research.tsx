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
import { ResearchCard } from "../components/ResearchCard";

export const S03_Research: React.FC = () => {
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

      <ChatThread
        messages={[
          {
            message: "Looked her up. Found what she cares about.",
            timestamp: "11:58 PM",
            delay: 8,
          },
        ]}
      />

      <div style={{ transform: `scale(${cardScale})` }}>
        <ResearchCard
          vcName="Sarah Chen"
          fund="Sequoia Capital"
          focus="Series A · B2B SaaS · $8–15M rounds"
          items={[
            {
              label: "Recent deals",
              value: "Notion, Linear, Loom — all productivity-layer SaaS",
            },
            {
              label: "Thesis",
              value: "Bets on tools that remove friction from knowledge work",
            },
            {
              label: "Portfolio overlap",
              value: "3 companies adjacent to your space",
            },
            {
              label: "Avg check size",
              value: "$10M, typically leads the round",
            },
          ]}
          enterDelay={30}
        />
      </div>
    </AbsoluteFill>
  );
};
