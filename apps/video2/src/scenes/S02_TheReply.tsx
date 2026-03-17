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
import { EmailThreadCard } from "../components/EmailThreadCard";

export const S02_TheReply: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const emailP = spring({
    frame: frame - 50,
    fps,
    config: { damping: 22, stiffness: 100 },
  });
  const emailOpacity = interpolate(emailP, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });
  const emailY = interpolate(emailP, [0, 1], [60, 0]);

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
        <Audio src={SFX.uiSwitch} volume={0.25} />
      </Sequence>
      <Sequence from={50}>
        <Audio src={SFX.uiSwitch} volume={0.2} />
      </Sequence>

      <ChatThread
        messages={[
          {
            message:
              "Sarah Chen at Sequoia replied. She wants your deck, latest metrics, and a time to meet.",
            timestamp: "11:52 PM",
            delay: 8,
          },
        ]}
      />

      <div
        style={{
          transform: `translateY(${emailY}px)`,
          opacity: emailOpacity,
        }}
      >
        <EmailThreadCard
          replyFrom="Sarah Chen"
          replySubject="Re: Quick question about your Series A"
          replyPreview="Hi — interesting timing, we've been looking at this space. Can you send over your current deck and..."
          replyTime="11:52 PM"
          originalSubject="Quick question about your Series A"
          originalPreview="Hi Sarah, following up on my note from last week..."
          enterDelay={50}
        />
      </div>
    </AbsoluteFill>
  );
};
