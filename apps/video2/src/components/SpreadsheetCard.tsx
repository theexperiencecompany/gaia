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
    config: { damping: 8, stiffness: 180 },
  });
  const cardOpacity = interpolate(cardP, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });
  const cardScale = interpolate(cardP, [0, 1], [0.88, 1]);

  return (
    <div
      style={{
        width: 1600,
        background: COLORS.surface,
        borderRadius: 32,
        overflow: "hidden",
        transform: `scale(${cardScale})`,
        opacity: cardOpacity,
      }}
    >
      <div
        style={{
          padding: "32px 44px",
          fontFamily: FONTS.display,
          fontSize: 52,
          fontWeight: 700,
          color: COLORS.textDark,
          background: COLORS.zinc900,
        }}
      >
        {title}
      </div>

      <div
        style={{
          display: "flex",
          background: "rgba(0,0,0,0.25)",
          padding: "18px 44px",
        }}
      >
        <div style={{ flex: 2 }} />
        {headers.map((h, i) => (
          <div
            key={i}
            style={{
              flex: 1,
              fontFamily: FONTS.body,
              fontSize: 30,
              fontWeight: 600,
              color: COLORS.zinc400,
              textAlign: "right",
            }}
          >
            {h}
          </div>
        ))}
      </div>

      {rows.map((row, rowIdx) => (
        <div
          key={rowIdx}
          style={{
            display: "flex",
            padding: "20px 44px",
            background: row.highlight
              ? "rgba(0, 187, 255, 0.07)"
              : rowIdx % 2 === 0
                ? "transparent"
                : "rgba(255,255,255,0.02)",
            borderLeft: row.highlight
              ? `5px solid rgba(0,187,255,0.5)`
              : "5px solid transparent",
          }}
        >
          <div
            style={{
              flex: 2,
              fontFamily: FONTS.body,
              fontSize: 36,
              color: row.highlight ? COLORS.primary : COLORS.zinc400,
              fontWeight: row.highlight ? 700 : 400,
            }}
          >
            {row.label}
          </div>
          {row.values.map((val, colIdx) => {
            const cellDelay = enterDelay + 15 + rowIdx * 8 + colIdx * 4;
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
                  flex: 1,
                  fontFamily: FONTS.mono,
                  fontSize: 36,
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
