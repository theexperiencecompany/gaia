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
    frame: frame - 15,
    fps,
    config: { damping: 18, stiffness: 120 },
  });
  const notifOpacity = interpolate(notifP, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });
  const notifY = interpolate(notifP, [0, 1], [-200, 0]);

  return (
    <AbsoluteFill
      style={{
        background: COLORS.bgLight,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      {/* SFX */}
      <Sequence from={15}>
        <Audio src={SFX.uiSwitch} volume={0.35} />
      </Sequence>

      {/* Notification card */}
      <div
        style={{
          width: 860,
          background: "rgba(30, 30, 32, 0.97)",
          borderRadius: 35,
          padding: "30px 40px 30px 25px",
          display: "flex",
          alignItems: "flex-start",
          gap: 20,
          transform: `translateY(${notifY}px)`,
          opacity: notifOpacity,
        }}
      >
        {/* Telegram icon */}
        <div
          style={{
            width: 96,
            height: 96,
            borderRadius: 20,
            background: "#229ed9",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontFamily: FONTS.display,
            fontSize: 36,
            fontWeight: 700,
            color: "#fff",
            flexShrink: 0,
          }}
        >
          T
        </div>

        <div style={{ flex: 1, paddingTop: 4 }}>
          {/* App label + timestamp */}
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              marginBottom: 10,
            }}
          >
            <span
              style={{
                fontFamily: FONTS.body,
                fontSize: 26,
                color: COLORS.zinc400,
                fontWeight: 500,
              }}
            >
              Telegram · GAIA
            </span>
            <span
              style={{
                fontFamily: FONTS.body,
                fontSize: 22,
                color: COLORS.zinc500,
              }}
            >
              now
            </span>
          </div>

          {/* Title */}
          <div
            style={{
              fontFamily: FONTS.body,
              fontSize: 40,
              fontWeight: 700,
              color: COLORS.textDark,
              marginBottom: 6,
            }}
          >
            The VC replied.
          </div>

          {/* Body */}
          <div
            style={{
              fontFamily: FONTS.body,
              fontSize: 30,
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
