import type React from "react";
import {
  AbsoluteFill,
  Audio,
  Sequence,
} from "remotion";
import { COLORS } from "../constants";
import { SFX } from "../sfx";
import { SpreadsheetCard } from "../components/SpreadsheetCard";

export const S05_DataRoom: React.FC = () => {
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

      <SpreadsheetCard
        title="Data Room · Q1 2026"
        headers={["Jan", "Feb", "Mar"]}
        rows={[
          {
            label: "MRR",
            values: ["$38K", "$43K", "$47K"],
            highlight: true,
          },
          {
            label: "Growth MoM",
            values: ["14%", "13%", "18%"],
            highlight: true,
          },
          { label: "Runway", values: ["—", "—", "14mo"] },
          { label: "Customers", values: ["1.8K", "2.1K", "2.4K"] },
          { label: "Churn", values: ["2.1%", "1.9%", "1.7%"] },
        ]}
        enterDelay={8}
      />
    </AbsoluteFill>
  );
};
