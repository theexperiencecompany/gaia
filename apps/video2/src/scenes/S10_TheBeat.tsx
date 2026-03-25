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

const TASKS = [
  { text: "Looked her up.", time: "11:58 PM" },
  { text: "Updated the deck.", time: "12:20 AM" },
  { text: "Data room cleaned up.", time: "1:15 AM" },
  { text: "Created a prep doc.", time: "2:30 AM" },
  { text: "Slacked your co-founder.", time: "5:00 AM" },
  { text: "Found 3 open slots.", time: "6:30 AM" },
  { text: "Wrote the reply.", time: "6:58 AM" },
];

interface TaskPillProps {
  text: string;
  time: string;
  appearFrame: number;
}

const TaskPill: React.FC<TaskPillProps> = ({ text, time, appearFrame }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  if (frame < appearFrame) return null;

  const p = spring({
    frame: frame - appearFrame,
    fps,
    config: { damping: 200 },
  });
  const opacity = interpolate(p, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });
  const x = interpolate(p, [0, 1], [-30, 0]);

  const checkP = spring({
    frame: frame - (appearFrame + 4),
    fps,
    config: { damping: 8, stiffness: 220 },
  });
  const checkScale = interpolate(checkP, [0, 1], [0, 1]);

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 18,
        opacity,
        transform: `translateX(${x}px)`,
      }}
    >
      <div
        style={{
          width: 36,
          height: 36,
          borderRadius: "50%",
          background: "#22c55e",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          flexShrink: 0,
          transform: `scale(${checkScale})`,
        }}
      >
        <svg width="18" height="14" viewBox="0 0 18 14" fill="none">
          <path
            d="M1.5 7L6.5 12L16.5 2"
            stroke="#000"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </div>
      <span
        style={{
          fontFamily: FONTS.body,
          fontSize: 34,
          fontWeight: 600,
          color: COLORS.textDark,
        }}
      >
        {text}
      </span>
      <span
        style={{
          fontFamily: FONTS.body,
          fontSize: 26,
          color: COLORS.zinc600,
          marginLeft: 4,
        }}
      >
        {time}
      </span>
    </div>
  );
};

export const S10_TheBeat: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const dimOpacity = interpolate(frame, [70, 90], [1, 0.3], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const qaP = spring({
    frame: frame - 88,
    fps,
    config: { damping: 200 },
  });
  const qaOpacity = interpolate(qaP, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });
  const qaY = interpolate(qaP, [0, 1], [20, 0]);

  const dot1 = frame >= 108 ? Math.sin((frame - 108) / 7) * 0.5 + 0.5 : 0;
  const dot2 =
    frame >= 108 ? Math.sin((frame - 108) / 7 + 1.2) * 0.5 + 0.5 : 0;
  const dot3 =
    frame >= 108 ? Math.sin((frame - 108) / 7 + 2.4) * 0.5 + 0.5 : 0;
  const showTyping = frame >= 108 && frame < 125;

  const replyP = spring({
    frame: frame - 125,
    fps,
    config: { damping: 200 },
  });
  const replyOpacity = interpolate(replyP, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });
  const replyScale = interpolate(replyP, [0, 1], [0.85, 1]);

  return (
    <AbsoluteFill
      style={{
        background: COLORS.bg,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        gap: 80,
      }}
    >
      <Sequence from={125}>
        <Audio src={SFX.whip} volume={0.55} />
      </Sequence>

      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 22,
          opacity: dimOpacity,
        }}
      >
        {TASKS.map((task, i) => (
          <TaskPill
            key={i}
            text={task.text}
            time={task.time}
            appearFrame={i * 8}
          />
        ))}
      </div>

      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 20,
          width: 580,
        }}
      >
        <div
          style={{
            transform: `translateY(${qaY}px)`,
            opacity: qaOpacity,
            display: "flex",
            alignItems: "flex-end",
            gap: 14,
          }}
        >
          <div
            style={{
              width: 44,
              height: 44,
              borderRadius: "50%",
              background: COLORS.primary,
              flexShrink: 0,
              marginBottom: 4,
            }}
          />
          <div
            style={{
              background: COLORS.surface,
              borderRadius: "40px 40px 40px 10px",
              padding: "24px 32px",
              fontFamily: FONTS.body,
              fontSize: 30,
              color: COLORS.zinc400,
              lineHeight: 1.45,
            }}
          >
            Ready to send. Want to review first, or just go?
          </div>
        </div>

        {showTyping && (
          <div
            style={{
              display: "flex",
              justifyContent: "flex-end",
            }}
          >
            <div
              style={{
                background: COLORS.primary,
                borderRadius: "40px 40px 10px 40px",
                padding: "20px 28px",
                display: "flex",
                gap: 10,
                alignItems: "center",
              }}
            >
              {[dot1, dot2, dot3].map((d, i) => (
                <div
                  key={i}
                  style={{
                    width: 12,
                    height: 12,
                    borderRadius: "50%",
                    background: "#000",
                    opacity: d,
                  }}
                />
              ))}
            </div>
          </div>
        )}

        <div
          style={{
            transform: `scale(${replyScale})`,
            opacity: replyOpacity,
            display: "flex",
            justifyContent: "flex-end",
          }}
        >
          <div
            style={{
              background: COLORS.primary,
              borderRadius: "40px 40px 10px 40px",
              padding: "26px 48px",
              fontFamily: FONTS.display,
              fontSize: 48,
              fontWeight: 800,
              color: "#000",
            }}
          >
            Send it.
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};
