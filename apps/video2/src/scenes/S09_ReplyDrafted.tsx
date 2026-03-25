import type React from "react";
import {
  AbsoluteFill,
  Audio,
  Sequence,
} from "remotion";
import { COLORS } from "../constants";
import { SFX } from "../sfx";
import { EmailComposeCard } from "../components/EmailComposeCard";

export const S09_ReplyDrafted: React.FC = () => {
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

      <EmailComposeCard
        to="sarah.chen@sequoia.com"
        subject="Re: Quick question about your Series A"
        body={"Hi Sarah,\n\nThanks for getting back — great timing.\n\nI've attached our deck and data room below. Happy to jump on a call this week."}
        attachments={["Series_A_Deck.pdf", "Data Room →", "Tue 2pm / Wed 10am / Thu 3pm"]}
        enterDelay={8}
        bodyTypingDelay={20}
        crmStatus="Replied"
      />
    </AbsoluteFill>
  );
};
