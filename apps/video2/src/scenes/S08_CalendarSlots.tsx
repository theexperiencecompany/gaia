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
import { CalendarSlotsCard } from "../components/CalendarSlotsCard";

export const S08_CalendarSlots: React.FC = () => {
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
              "Found 3 open slots. Added a 30-min prep block before each.",
            timestamp: "6:30 AM",
            delay: 8,
          },
        ]}
      />

      <div style={{ transform: `scale(${cardScale})` }}>
        <CalendarSlotsCard
          enterDelay={30}
          slots={[
            { day: "Tuesday", time: "2:00 PM", prepTime: "1:30 PM" },
            { day: "Wednesday", time: "10:00 AM", prepTime: "9:30 AM" },
            { day: "Thursday", time: "3:00 PM", prepTime: "2:30 PM" },
          ]}
        />
      </div>
    </AbsoluteFill>
  );
};
