import type React from "react";
import {
  AbsoluteFill,
  Audio,
  Sequence,
} from "remotion";
import { COLORS } from "../constants";
import { SFX } from "../sfx";
import { EmailThreadCard } from "../components/EmailThreadCard";

export const S02_TheReply: React.FC = () => {
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
        <Audio src={SFX.uiSwitch} volume={0.25} />
      </Sequence>

      <EmailThreadCard
        replyFrom="Sarah Chen"
        replySubject="Re: Quick question about your Series A"
        replyPreview="Hi — interesting timing, we've been looking at this space. Can you send over your current deck and..."
        replyTime="11:52 PM"
        originalSubject="Quick question about your Series A"
        originalPreview="Hi Sarah, following up on my note from last week..."
        enterDelay={8}
      />
    </AbsoluteFill>
  );
};
