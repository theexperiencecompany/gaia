import type React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { COLORS, FONTS } from "../constants";

interface SpreadsheetRow {
  label: string;
  values: string[];
  highlight?: boolean;
}

interface SpreadsheetCardProps {
  title: string;
  headers: string[];
  rows: SpreadsheetRow[];
  enterDelay?: number;
}

export const SpreadsheetCard: React.FC<SpreadsheetCardProps> = ({
  title,
  headers,
  rows,
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
      {/* Title */}
      <div
        style={{
          padding: "22px 28px",
          fontFamily: FONTS.body,
          fontSize: 26,
          fontWeight: 700,
          color: COLORS.textDark,
          borderBottom: `1px solid ${COLORS.zinc700}`,
        }}
      >
        {title}
      </div>

      {/* Header row */}
      <div
        style={{
          display: "flex",
          background: COLORS.zinc900,
          borderBottom: `1px solid ${COLORS.zinc700}`,
          padding: "12px 28px",
        }}
      >
        <div style={{ width: 220, fontFamily: FONTS.body, fontSize: 20, fontWeight: 600, color: COLORS.zinc400 }}>
          {/* empty label column */}
        </div>
        {headers.map((h, i) => (
          <div
            key={i}
            style={{
              width: 180,
              fontFamily: FONTS.body,
              fontSize: 20,
              fontWeight: 600,
              color: COLORS.zinc400,
              textAlign: "right",
            }}
          >
            {h}
          </div>
        ))}
      </div>

      {/* Data rows */}
      {rows.map((row, rowIdx) => (
        <div
          key={rowIdx}
          style={{
            display: "flex",
            padding: "12px 28px",
            background: row.highlight ? "rgba(0, 187, 255, 0.06)" : "transparent",
            borderBottom: `1px solid ${COLORS.zinc700}`,
            borderLeft: row.highlight ? "3px solid rgba(0,187,255,0.4)" : "none",
          }}
        >
          <div
            style={{
              width: 220,
              fontFamily: FONTS.body,
              fontSize: 24,
              color: row.highlight ? COLORS.primary : COLORS.zinc400,
              fontWeight: row.highlight ? 600 : 400,
            }}
          >
            {row.label}
          </div>
          {row.values.map((val, colIdx) => {
            const cellDelay = (enterDelay + 15) + rowIdx * 8 + colIdx * 4;
            const cellP = spring({
              frame: frame - cellDelay,
              fps,
              config: { damping: 200 },
            });
            const cellOpacity = interpolate(cellP, [0, 0.1], [0, 1], {
              extrapolateRight: "clamp",
            });

            return (
              <div
                key={colIdx}
                style={{
                  width: 180,
                  fontFamily: FONTS.mono,
                  fontSize: 24,
                  color: row.highlight ? COLORS.primary : COLORS.textDark,
                  fontWeight: row.highlight ? 700 : 400,
                  textAlign: "right",
                  opacity: cellOpacity,
                }}
              >
                {val}
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );
};
