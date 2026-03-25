import type React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { COLORS, FONTS } from "../constants";

interface Slide {
  title: string;
  highlight?: boolean;
  metric?: string;
  metricLabel?: string;
}

interface DeckSlidesCardProps {
  slides: Slide[];
  enterDelay?: number;
}

export const DeckSlidesCard: React.FC<DeckSlidesCardProps> = ({
  slides,
  enterDelay = 0,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const getFanOffset = (index: number, total: number) => {
    const center = (total - 1) / 2;
    const offset = (index - center) * 160;
    const rotation = (index - center) * 5;
    return { offsetX: offset, rotation };
  };

  return (
    <div
      style={{
        width: 1600,
        height: 700,
        position: "relative",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      {slides.map((slide, i) => {
        const slideDelay = enterDelay + i * 8;
        const slideP = spring({
          frame: frame - slideDelay,
          fps,
          config: { damping: 8, stiffness: 180 },
        });
        const slideOpacity = interpolate(slideP, [0, 0.1], [0, 1], {
          extrapolateRight: "clamp",
        });
        const { offsetX, rotation } = getFanOffset(i, slides.length);
        const currentX = interpolate(slideP, [0, 1], [0, offsetX]);
        const currentRot = interpolate(slideP, [0, 1], [0, rotation]);

        return (
          <div
            key={i}
            style={{
              position: "absolute",
              width: 600,
              height: 420,
              borderRadius: 24,
              background: slide.highlight ? COLORS.zinc900 : COLORS.surface,
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
              padding: "32px 36px",
              transform: `translateX(${currentX}px) rotate(${currentRot}deg)`,
              opacity: slideOpacity,
              zIndex: slide.highlight ? slides.length + 1 : i,
              boxShadow: slide.highlight
                ? "0 0 80px rgba(0,187,255,0.18)"
                : "none",
            }}
          >
            <div
              style={{
                fontFamily: FONTS.body,
                fontSize: 30,
                fontWeight: 600,
                color: slide.highlight ? COLORS.primary : COLORS.zinc400,
                marginBottom: slide.metric ? 16 : 0,
                textAlign: "center",
              }}
            >
              {slide.title}
            </div>
            {slide.metric && (
              <>
                <div
                  style={{
                    fontFamily: FONTS.display,
                    fontSize: 120,
                    fontWeight: 800,
                    color: COLORS.textDark,
                    lineHeight: 1,
                  }}
                >
                  {slide.metric}
                </div>
                {slide.metricLabel && (
                  <div
                    style={{
                      fontFamily: FONTS.body,
                      fontSize: 28,
                      color: COLORS.zinc400,
                      marginTop: 10,
                    }}
                  >
                    {slide.metricLabel}
                  </div>
                )}
              </>
            )}
          </div>
        );
      })}
    </div>
  );
};
