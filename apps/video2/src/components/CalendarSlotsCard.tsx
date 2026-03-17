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

  const cardP = spring({
    frame: frame - enterDelay,
    fps,
    config: { damping: 22, stiffness: 100 },
  });
  const cardOpacity = interpolate(cardP, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });
  const cardY = interpolate(cardP, [0, 1], [40, 0]);
  const cardScale = interpolate(cardP, [0, 1], [0.95, 1]);

  return (
    <div
      style={{
        width: 860,
        background: COLORS.surface,
        borderRadius: 28,
        overflow: "hidden",
        transform: `translateY(${cardY}px) scale(${cardScale})`,
        opacity: cardOpacity,
      }}
    >
      {/* Header */}
      <div
        style={{
          padding: "22px 32px",
          borderBottom: `1px solid ${COLORS.zinc700}`,
        }}
      >
        <div
          style={{
            fontFamily: FONTS.body,
            fontSize: 26,
            fontWeight: 700,
            color: COLORS.textDark,
            marginBottom: 4,
          }}
        >
          Calendar
        </div>
        <div
          style={{
            fontFamily: FONTS.body,
            fontSize: 22,
            color: COLORS.zinc500,
          }}
        >
          {slots.length} slots found · prep blocks added
        </div>
      </div>

      {/* Slots */}
      <div style={{ padding: "16px 24px", display: "flex", flexDirection: "column", gap: 12 }}>
        {slots.map((slot, i) => {
          const slotDelay = (enterDelay + 15) + i * 10;
          const prepDelay = slotDelay + 8;

          const slotP = spring({
            frame: frame - slotDelay,
            fps,
            config: { damping: 200 },
          });
          const slotOpacity = interpolate(slotP, [0, 0.1], [0, 1], {
            extrapolateRight: "clamp",
          });
          const slotY = interpolate(slotP, [0, 1], [20, 0]);

          const prepP = spring({
            frame: frame - prepDelay,
            fps,
            config: { damping: 200 },
          });
          const prepOpacity = interpolate(prepP, [0, 0.1], [0, 1], {
            extrapolateRight: "clamp",
          });

          return (
            <div key={i} style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {/* Prep block */}
              <div
                style={{
                  background: "rgba(0, 187, 255, 0.08)",
                  border: `1px dashed ${COLORS.primary}`,
                  borderRadius: 12,
                  padding: "10px 18px",
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  opacity: prepOpacity,
                }}
              >
                <div
                  style={{
                    width: 8,
                    height: 8,
                    borderRadius: "50%",
                    background: COLORS.primary,
                    flexShrink: 0,
                  }}
                />
                <span
                  style={{
                    fontFamily: FONTS.body,
                    fontSize: 20,
                    color: COLORS.primary,
                  }}
                >
                  {slot.day} · {slot.prepTime} — Prep
                </span>
              </div>

              {/* Meeting slot */}
              <div
                style={{
                  background: COLORS.primary,
                  borderRadius: 12,
                  padding: "14px 18px",
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  transform: `translateY(${slotY}px)`,
                  opacity: slotOpacity,
                }}
              >
                <span
                  style={{
                    fontFamily: FONTS.body,
                    fontSize: 24,
                    fontWeight: 700,
                    color: "#000",
                  }}
                >
                  {slot.day}
                </span>
                <span
                  style={{
                    fontFamily: FONTS.body,
                    fontSize: 22,
                    fontWeight: 600,
                    color: "#000",
                  }}
                >
                  {slot.time}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
