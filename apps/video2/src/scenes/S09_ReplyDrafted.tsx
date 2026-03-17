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
import { EmailComposeCard } from "../components/EmailComposeCard";

export const S09_ReplyDrafted: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const scaleP = spring({
    frame: frame - 35,
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

      <ChatThread
        messages={[
          {
            message:
              "Wrote your reply. Deck, data room, and 3 time slots attached.",
            timestamp: "6:58 AM",
            delay: 8,
          },
        ]}
      />

      <div style={{ transform: `scale(${cardScale})` }}>
        <EmailComposeCard
          to="sarah.chen@sequoia.com"
          subject="Re: Quick question about your Series A"
          body={"Hi Sarah,\n\nThanks for getting back — great timing.\n\nI've attached our deck and data room below. Happy to jump on a call this week."}
          attachments={["Series_A_Deck.pdf", "Data Room →", "Tue 2pm / Wed 10am / Thu 3pm"]}
          enterDelay={25}
          bodyTypingDelay={35}
          crmStatus="Replied"
        />
      </div>
    </AbsoluteFill>
  );
};
