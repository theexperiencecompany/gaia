import type React from "react";
import {
  AbsoluteFill,
  Audio,
  Sequence,
} from "remotion";
import { COLORS } from "../constants";
import { SFX } from "../sfx";
import { SlackMessageCard } from "../components/SlackMessageCard";

export const S07_SlackNotify: React.FC = () => {
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
      <Sequence from={20}>
        <Audio src={SFX.uiSwitch} volume={0.25} />
      </Sequence>

      <SlackMessageCard
        workspace="Company"
        channel="founders"
        from="GAIA"
        message="Heads up — Sequoia replied. Meeting likely this week. Deck updated, data room clean, prep doc ready."
        enterDelay={8}
      />
    </AbsoluteFill>
  );
};
