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
import { SpreadsheetCard } from "../components/SpreadsheetCard";

export const S05_DataRoom: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const scaleP = spring({
    frame: frame - 35,
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
      <Sequence from={35}>
        <Audio src={SFX.uiSwitch} volume={0.2} />
      </Sequence>

      <ChatThread
        messages={[
          {
            message:
              "Data room cleaned up. Every number she'll dig into is there.",
            timestamp: "1:15 AM",
            delay: 8,
          },
        ]}
      />

      <div style={{ transform: `scale(${cardScale})` }}>
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
          enterDelay={25}
        />
      </div>
    </AbsoluteFill>
  );
};
