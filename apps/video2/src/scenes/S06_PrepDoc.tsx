import type React from "react";
import {
  AbsoluteFill,
  Audio,
  Sequence,
} from "remotion";
import { COLORS } from "../constants";
import { SFX } from "../sfx";
import { PrepDocCard } from "../components/PrepDocCard";

export const S06_PrepDoc: React.FC = () => {
  return (
    <AbsoluteFill
      style={{
        background: COLORS.bg,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <Sequence from={8}>
        <Audio src={SFX.whoosh} volume={0.2} />
      </Sequence>

      <PrepDocCard
        title="Sequoia Meeting Prep"
        enterDelay={8}
        questions={[
          {
            question: "What's your CAC payback period?",
            talkingPoint: "4 months — below our Series A benchmark of 6.",
          },
          {
            question: "Who's your biggest competitor?",
            talkingPoint:
              "No direct comp. Zapier & Notion AI don't do proactive automation.",
          },
          {
            question: "Why now?",
            talkingPoint:
              "LLM costs down 10x in 18 months — makes real-time proactive agents viable.",
          },
          {
            question: "What does the $10M go toward?",
            talkingPoint: "40% eng hiring, 35% GTM, 25% infra scale.",
          },
        ]}
      />
    </AbsoluteFill>
  );
};
