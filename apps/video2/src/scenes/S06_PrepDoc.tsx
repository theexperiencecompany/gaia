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
import { PrepDocCard } from "../components/PrepDocCard";

export const S06_PrepDoc: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const scaleP = spring({
    frame: frame - 40,
    fps,
    config: { damping: 22, stiffness: 100 },
  });
  const cardScale = interpolate(scaleP, [0, 1], [1, 1.06]);

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
        <Audio src={SFX.uiSwitch} volume={0.2} />
      </Sequence>

      <ChatThread
        messages={[
          {
            message:
              "Created a prep doc — likely questions she'll ask with your talking points.",
            timestamp: "2:30 AM",
            delay: 8,
          },
        ]}
      />

      <div style={{ transform: `scale(${cardScale})` }}>
        <PrepDocCard
          title="Sequoia Meeting Prep"
          enterDelay={30}
          questions={[
            {
              question: "What's your CAC payback period?",
              talkingPoint:
                "Currently 4 months — below our Series A benchmark of 6.",
            },
            {
              question: "Who's your biggest competitor?",
              talkingPoint:
                "No direct comp. Adjacent players (Zapier, Notion AI) don't do proactive automation.",
            },
            {
              question: "Why now?",
              talkingPoint:
                "LLM costs down 10x in 18 months — makes real-time proactive agents viable at our price point.",
            },
            {
              question: "What does the $10M go toward?",
              talkingPoint: "40% eng hiring, 35% GTM, 25% infra scale.",
            },
          ]}
        />
      </div>
    </AbsoluteFill>
  );
};
