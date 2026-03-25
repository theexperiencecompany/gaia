import type React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { COLORS, FONTS } from "../constants";

interface CalendarSlot {
  day: string;
  time: string;
  prepTime: string;
}

interface CalendarSlotsCardProps {
  slots: CalendarSlot[];
  enterDelay?: number;
}

export const CalendarSlotsCard: React.FC<CalendarSlotsCardProps> = ({
  slots,
  enterDelay = 0,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  return (
    <div
      style={{
        display: "flex",
        gap: 28,
      }}
    >
      {slots.map((slot, i) => {
        const slotDelay = enterDelay + i * 14;
        const slotP = spring({
          frame: frame - slotDelay,
          fps,
          config: { damping: 8, stiffness: 180 },
        });
        const slotOpacity = interpolate(slotP, [0, 0.1], [0, 1], {
          extrapolateRight: "clamp",
        });
        const slotScale = interpolate(slotP, [0, 1], [0.84, 1]);

        const prepDelay = slotDelay + 10;
        const prepP = spring({
          frame: frame - prepDelay,
          fps,
          config: { damping: 200 },
        });
        const prepOpacity = interpolate(prepP, [0, 0.1], [0, 1], {
          extrapolateRight: "clamp",
        });

        return (
          <div
            key={i}
            style={{
              width: 430,
              background: COLORS.surface,
              borderRadius: 32,
              padding: "48px 44px",
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              gap: 8,
              transform: `scale(${slotScale})`,
              opacity: slotOpacity,
            }}
          >
            <div
              style={{
                fontFamily: FONTS.body,
                fontSize: 36,
                fontWeight: 600,
                color: COLORS.zinc400,
                letterSpacing: "0.02em",
              }}
            >
              {slot.day}
            </div>
            <div
              style={{
                fontFamily: FONTS.display,
                fontSize: 96,
                fontWeight: 800,
                color: COLORS.primary,
                lineHeight: 1,
              }}
            >
              {slot.time}
            </div>
            <div
              style={{
                fontFamily: FONTS.body,
                fontSize: 26,
                color: COLORS.zinc500,
                marginTop: 8,
                opacity: prepOpacity,
              }}
            >
              Prep at {slot.prepTime}
            </div>
          </div>
        );
      })}
    </div>
  );
};
