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

export const S01_Notification: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const notifP = spring({
    frame: frame - 12,
    fps,
    config: { damping: 12, stiffness: 160 },
  });
  const notifOpacity = interpolate(notifP, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });
  const notifY = interpolate(notifP, [0, 1], [-180, 0]);

  return (
    <AbsoluteFill
      style={{
        background: COLORS.bg,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <Sequence from={12}>
        <Audio src={SFX.uiSwitch} volume={0.35} />
      </Sequence>

      <div
        style={{
          width: 1200,
          background: "rgba(30, 30, 32, 0.97)",
          borderRadius: 40,
          padding: "40px 52px 40px 36px",
          display: "flex",
          alignItems: "flex-start",
          gap: 28,
          transform: `translateY(${notifY}px)`,
          opacity: notifOpacity,
        }}
      >
        <div
          style={{
            width: 120,
            height: 120,
            borderRadius: 28,
            background: "#229ed9",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontFamily: FONTS.display,
            fontSize: 52,
            fontWeight: 700,
            color: "#fff",
            flexShrink: 0,
          }}
        >
          T
        </div>

        <div style={{ flex: 1, paddingTop: 6 }}>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              marginBottom: 12,
            }}
          >
            <span
              style={{
                fontFamily: FONTS.body,
                fontSize: 34,
                color: COLORS.zinc400,
                fontWeight: 500,
              }}
            >
              Telegram · GAIA
            </span>
            <span
              style={{
                fontFamily: FONTS.body,
                fontSize: 30,
                color: COLORS.zinc500,
              }}
            >
              now
            </span>
          </div>

          <div
            style={{
              fontFamily: FONTS.display,
              fontSize: 56,
              fontWeight: 700,
              color: COLORS.textDark,
              marginBottom: 8,
            }}
          >
            The VC replied.
          </div>

          <div
            style={{
              fontFamily: FONTS.body,
              fontSize: 38,
              color: COLORS.zinc400,
              lineHeight: 1.4,
            }}
          >
            I've handled everything overnight.
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};
