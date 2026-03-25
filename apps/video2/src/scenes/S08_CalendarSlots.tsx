import type React from "react";
import {
  AbsoluteFill,
  Audio,
  Sequence,
} from "remotion";
import { COLORS } from "../constants";
import { SFX } from "../sfx";
import { CalendarSlotsCard } from "../components/CalendarSlotsCard";

export const S08_CalendarSlots: React.FC = () => {
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

      <CalendarSlotsCard
        enterDelay={8}
        slots={[
          { day: "Tuesday", time: "2:00 PM", prepTime: "1:30 PM" },
          { day: "Wednesday", time: "10:00 AM", prepTime: "9:30 AM" },
          { day: "Thursday", time: "3:00 PM", prepTime: "2:30 PM" },
        ]}
      />
    </AbsoluteFill>
  );
};
