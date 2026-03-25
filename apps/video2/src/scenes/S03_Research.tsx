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
import { COLORS, FONTS } from "../constants";
import { SFX } from "../sfx";

const ITEMS = [
  { label: "Recent deals", value: "Notion, Linear, Loom" },
  { label: "Thesis", value: "Removes friction from knowledge work" },
  { label: "Portfolio overlap", value: "3 companies adjacent to you" },
  { label: "Avg check size", value: "$10M, leads the round" },
];

export const S03_Research: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const nameP = spring({
    frame: frame - 8,
    fps,
    config: { damping: 200 },
  });
  const nameOpacity = interpolate(nameP, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });
  const nameX = interpolate(nameP, [0, 1], [-50, 0]);

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

      <div
        style={{
          display: "flex",
          width: 1700,
          gap: 80,
          alignItems: "center",
        }}
      >
        <div
          style={{
            flex: 1,
            transform: `translateX(${nameX}px)`,
            opacity: nameOpacity,
          }}
        >
          <div
            style={{
              fontFamily: FONTS.display,
              fontSize: 96,
              fontWeight: 800,
              color: COLORS.textDark,
              lineHeight: 1,
              marginBottom: 16,
            }}
          >
            Sarah Chen
          </div>
          <div
            style={{
              fontFamily: FONTS.display,
              fontSize: 52,
              fontWeight: 700,
              color: COLORS.primary,
              marginBottom: 12,
            }}
          >
            Sequoia Capital
          </div>
          <div
            style={{
              fontFamily: FONTS.body,
              fontSize: 34,
              color: COLORS.zinc400,
            }}
          >
            Series A · B2B SaaS · $8–15M
          </div>
        </div>

        <div
          style={{
            flex: 1,
            display: "grid",
            gridTemplateColumns: "1fr 1fr",
            gap: 20,
          }}
        >
          {ITEMS.map((item, i) => {
            const cardDelay = 18 + i * 12;
            const cardP = spring({
              frame: frame - cardDelay,
              fps,
              config: { damping: 8, stiffness: 180 },
            });
            const cardOpacity = interpolate(cardP, [0, 0.1], [0, 1], {
              extrapolateRight: "clamp",
            });
            const cardScale = interpolate(cardP, [0, 1], [0.84, 1]);

            return (
              <div
                key={i}
                style={{
                  background: COLORS.surface,
                  borderRadius: 24,
                  padding: "36px 38px",
                  transform: `scale(${cardScale})`,
                  opacity: cardOpacity,
                }}
              >
                <div
                  style={{
                    fontFamily: FONTS.body,
                    fontSize: 24,
                    color: COLORS.zinc400,
                    marginBottom: 10,
                  }}
                >
                  {item.label}
                </div>
                <div
                  style={{
                    fontFamily: FONTS.body,
                    fontSize: 30,
                    fontWeight: 700,
                    color: COLORS.textDark,
                    lineHeight: 1.3,
                  }}
                >
                  {item.value}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </AbsoluteFill>
  );
};
