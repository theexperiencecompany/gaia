import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig, spring, interpolate } from "remotion";
import { COLORS, FONTS } from "../constants";

const BEATS = [
  {
    headline: "Create your own.",
    sub: "Build workflows with natural language",
    color: COLORS.textDark,
    accent: "+",
    accentColor: COLORS.primary,
    start: 0,
    end: 30,
  },
  {
    headline: "Publish them.",
    sub: "Share with anyone, anywhere",
    color: COLORS.primary,
    accent: "↑",
    accentColor: COLORS.primary,
    start: 28,
    end: 62,
  },
  {
    headline: "Browse the community.",
    sub: "Thousands of community workflows",
    color: COLORS.textDark,
    accent: "⊞",
    accentColor: COLORS.primary,
    start: 60,
    end: 102,
  },
];

interface BeatProps {
  beat: (typeof BEATS)[number];
  isActive: boolean;
  localFrame: number;
  fps: number;
}

const Beat: React.FC<BeatProps> = ({ beat, isActive, localFrame, fps }) => {
  const enterProgress = spring({ frame: localFrame, fps, config: { damping: 200 } });
  const exitProgress = spring({
    frame: localFrame - (beat.end - beat.start - 12),
    fps,
    config: { damping: 200 },
  });

  const opacity =
    localFrame < 0
      ? 0
      : localFrame > beat.end - beat.start - 12
      ? interpolate(exitProgress, [0, 1], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })
      : interpolate(enterProgress, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });

  const scale =
    localFrame > beat.end - beat.start - 12
      ? interpolate(exitProgress, [0, 1], [1, 1.08], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })
      : 1;

  if (!isActive && localFrame < 0) return null;

  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 24,
        opacity,
        transform: `scale(${scale})`,
      }}
    >
      <div
        style={{
          fontFamily: FONTS.display,
          fontSize: beat.headline.length > 14 ? 140 : 160,
          color: beat.color,
          textAlign: "center",
          lineHeight: 1.05,
        }}
      >
        {beat.headline}
      </div>
      <div
        style={{
          fontFamily: FONTS.body,
          fontSize: 32,
          fontWeight: 400,
          color: COLORS.zinc600,
          textAlign: "center",
        }}
      >
        {beat.sub}
      </div>
    </div>
  );
};

export const S26_CreatePublishBrowse: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  return (
    <AbsoluteFill style={{ background: COLORS.bgLight }}>
      {BEATS.map((beat, i) => {
        const localFrame = frame - beat.start;
        const isActive = frame >= beat.start && frame <= beat.end;
        return (
          <Beat
            key={i}
            beat={beat}
            isActive={isActive || frame > beat.start}
            localFrame={localFrame}
            fps={fps}
          />
        );
      })}
    </AbsoluteFill>
  );
};
