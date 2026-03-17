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

  // Fan offsets: alternate left/right with increasing offset
  const getFanOffset = (index: number, total: number) => {
    const center = (total - 1) / 2;
    const offset = (index - center) * 120;
    const rotation = (index - center) * 6;
    return { offsetX: offset, rotation };
  };

  return (
    <div
      style={{
        width: 900,
        height: 520,
        position: "relative",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      {slides.map((slide, i) => {
        const slideDelay = enterDelay + i * 6;
        const slideP = spring({
          frame: frame - slideDelay,
          fps,
          config: { damping: 22, stiffness: 100 },
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
              width: 400,
              height: 280,
              borderRadius: 20,
              background: slide.highlight ? COLORS.zinc900 : COLORS.surface,
              border: slide.highlight ? `2px solid ${COLORS.primary}` : "none",
              boxShadow: slide.highlight ? "0 0 40px rgba(0,187,255,0.2)" : "none",
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
              padding: "24px 28px",
              transform: `translateX(${currentX}px) rotate(${currentRot}deg)`,
              opacity: slideOpacity,
              zIndex: slide.highlight ? slides.length + 1 : i,
            }}
          >
            <div
              style={{
                fontFamily: FONTS.body,
                fontSize: 22,
                fontWeight: 600,
                color: slide.highlight ? COLORS.primary : COLORS.zinc400,
                marginBottom: slide.metric ? 12 : 0,
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
                    fontSize: 72,
                    fontWeight: 700,
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
                      fontSize: 22,
                      color: COLORS.zinc400,
                      marginTop: 8,
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
