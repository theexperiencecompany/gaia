import type React from "react";
import {
  AbsoluteFill,
  Audio,
  Img,
  interpolate,
  Sequence,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { SceneBackground } from "../components/SceneBackground";
import { COLORS, FONTS } from "../constants";
import { SFX } from "../sfx";
import { BotTail } from "./S06_UserChat";

const MESSAGE =
  "Noticed your Q4 review moved to 3pm.\nUpdated your calendar. Emailed your team.";

const CARD_DELAY_CAL = 8;
const CARD_DELAY_EMAIL = 28;
const BUBBLE_DELAY = 52;

const CALENDAR_EVENTS = [
  { title: "Q4 Review", time: "3:00 – 4:00 PM", color: COLORS.primary },
  { title: "Prep Block · added", time: "2:30 – 3:00 PM", color: "#60a5fa" },
];

interface CardAnimProps {
  delay: number;
}

const CalendarEventCard: React.FC<CardAnimProps> = ({ delay }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = spring({
    frame: frame - delay,
    fps,
    config: { damping: 22, stiffness: 100 },
  });
  const opacity = interpolate(p, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });
  const cardY = interpolate(p, [0, 1], [40, 0]);
  const cardScale = interpolate(p, [0, 1], [0.94, 1.0]);

  return (
    <div
      style={{
        borderRadius: 28,
        background: "#27272a",
        padding: 24,
        height: "100%",
        boxSizing: "border-box",
        transform: `translateY(${cardY}px) scale(${cardScale})`,
        opacity,
      }}
    >
      {/* Date separator */}
      <div style={{ display: "flex", alignItems: "center", marginBottom: 16 }}>
        <div style={{ flex: 1, height: 1, background: "#3f3f46" }} />
        <span
          style={{
            padding: "0 16px",
            fontSize: 22,
            color: "#71717a",
            fontFamily: FONTS.body,
          }}
        >
          Today
        </span>
        <div style={{ flex: 1, height: 1, background: "#3f3f46" }} />
      </div>

      {/* Event rows */}
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {CALENDAR_EVENTS.map((event, i) => (
          <div
            key={`cal-${i}`}
            style={{
              position: "relative",
              display: "flex",
              alignItems: "flex-start",
              borderRadius: 10,
              padding: "18px 16px 18px 28px",
              backgroundColor: `${event.color}20`,
            }}
          >
            <div
              style={{
                position: "absolute",
                left: 6,
                top: 0,
                bottom: 0,
                display: "flex",
                alignItems: "center",
              }}
            >
              <div
                style={{
                  width: 4,
                  height: "80%",
                  borderRadius: 2,
                  backgroundColor: event.color,
                }}
              />
            </div>
            <div>
              <div
                style={{
                  fontSize: 30,
                  color: "white",
                  fontFamily: FONTS.body,
                  fontWeight: 500,
                  lineHeight: 1.3,
                }}
              >
                {event.title}
              </div>
              <div
                style={{
                  fontSize: 22,
                  color: "#a1a1aa",
                  fontFamily: FONTS.body,
                  marginTop: 4,
                }}
              >
                {event.time}
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Added button */}
      <div
        style={{
          marginTop: 18,
          width: "100%",
          padding: "14px 0",
          borderRadius: 999,
          background: `${COLORS.primary}20`,
          color: COLORS.primary,
          fontSize: 22,
          fontWeight: 600,
          fontFamily: FONTS.body,
          textAlign: "center",
        }}
      >
        Added to Calendar
      </div>
    </div>
  );
};

const EMAIL_BODY =
  "Hi team,\n\nQ4 review has been moved to 3:00 PM today.\nCalendar invite updated — see you there!";

const EmailComposeCard: React.FC<CardAnimProps> = ({ delay }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = spring({
    frame: frame - delay,
    fps,
    config: { damping: 22, stiffness: 100 },
  });
  const opacity = interpolate(p, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });
  const cardY = interpolate(p, [0, 1], [40, 0]);
  const cardScale = interpolate(p, [0, 1], [0.94, 1.0]);

  const sep = (
    <div style={{ height: 1, background: "#3f3f46", margin: "8px 0" }} />
  );

  return (
    <div
      style={{
        borderRadius: 28,
        background: "#27272a",
        overflow: "hidden",
        height: "100%",
        boxSizing: "border-box",
        transform: `translateY(${cardY}px) scale(${cardScale})`,
        opacity,
      }}
    >
      {/* Header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          padding: "20px 32px 14px",
        }}
      >
        <Img
          src={staticFile("images/icons/gmail.svg")}
          style={{ width: 28, height: 28, objectFit: "contain" }}
        />
        <span
          style={{
            fontSize: 26,
            fontWeight: 600,
            color: "white",
            fontFamily: FONTS.body,
          }}
        >
          Compose Email
        </span>
      </div>

      {/* Fields */}
      <div style={{ padding: "0 32px" }}>
        <div
          style={{
            display: "flex",
            gap: 10,
            fontSize: 22,
            fontFamily: FONTS.body,
            paddingBottom: 10,
          }}
        >
          <span style={{ color: "#a1a1aa" }}>To:</span>
          <span style={{ color: "#e4e4e7", fontWeight: 500 }}>
            sarah@company.com, david@company.com
          </span>
        </div>
        {sep}

        <div
          style={{
            display: "flex",
            gap: 10,
            fontSize: 22,
            fontFamily: FONTS.body,
            paddingBottom: 10,
          }}
        >
          <span style={{ color: "#a1a1aa" }}>Subject:</span>
          <span style={{ color: "#e4e4e7", fontWeight: 500 }}>
            Q4 Review rescheduled
          </span>
        </div>
        {sep}

        <div
          style={{
            fontSize: 21,
            color: "#d4d4d8",
            fontFamily: FONTS.body,
            lineHeight: 1.65,
            whiteSpace: "pre-wrap",
            paddingBottom: 20,
          }}
        >
          {EMAIL_BODY}
        </div>
      </div>

      {/* Sent button */}
      <div
        style={{
          padding: "0 32px 24px",
          display: "flex",
          justifyContent: "flex-end",
        }}
      >
        <div
          style={{
            padding: "11px 36px",
            borderRadius: 999,
            background: "#34d39920",
            color: "#34d399",
            fontSize: 22,
            fontWeight: 600,
            fontFamily: FONTS.body,
          }}
        >
          Sent
        </div>
      </div>
    </div>
  );
};

export const S21b_ProactiveNudge: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const headlineP = spring({ frame, fps, config: { damping: 200 } });
  const headlineOpacity = interpolate(headlineP, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });
  const headlineY = interpolate(headlineP, [0, 1], [20, 0]);

  const bubbleP = spring({
    frame: frame - BUBBLE_DELAY,
    fps,
    config: { damping: 25 },
  });
  const bubbleY = interpolate(bubbleP, [0, 1], [24, 0]);
  const bubbleOpacity = interpolate(bubbleP, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill>
      <Sequence from={0}>
        <Audio src={SFX.whoosh} volume={0.3} />
      </Sequence>
      <Sequence from={CARD_DELAY_CAL}>
        <Audio src={SFX.uiSwitch} volume={0.22} />
      </Sequence>
      <Sequence from={CARD_DELAY_EMAIL}>
        <Audio src={SFX.uiSwitch} volume={0.22} />
      </Sequence>
      <Sequence from={BUBBLE_DELAY}>
        <Audio src={SFX.whoosh} volume={0.25} />
      </Sequence>

      <SceneBackground variant="light" />

      <div
        style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          flexDirection: "column",
          padding: "52px 100px",
          gap: 20,
        }}
      >
        {/* Headline */}
        <div
          style={{
            transform: `translateY(${headlineY}px)`,
            opacity: headlineOpacity,
          }}
        >
          <span
            style={{
              fontFamily: FONTS.display,
              textTransform: "uppercase",
              fontSize: 72,
              fontWeight: 700,
              color: COLORS.textDark,
              letterSpacing: "-0.01em",
            }}
          >
            Acts before you ask.
          </span>
        </div>

        {/* Cards — side by side */}
        <div style={{ display: "flex", gap: 20, flex: 1, minHeight: 0 }}>
          <div style={{ flex: 1 }}>
            <CalendarEventCard delay={CARD_DELAY_CAL} />
          </div>
          <div style={{ flex: 1 }}>
            <EmailComposeCard delay={CARD_DELAY_EMAIL} />
          </div>
        </div>

        {/* Bot bubble */}
        <div
          style={{
            display: "flex",
            alignItems: "flex-start",
            gap: 20,
            transform: `translateY(${bubbleY}px)`,
            opacity: bubbleOpacity,
          }}
        >
          <Img
            src={staticFile("images/logos/logo.webp")}
            style={{
              width: 64,
              height: 64,
              borderRadius: "50%",
              objectFit: "contain",
              flexShrink: 0,
              marginTop: 4,
            }}
          />
          <div style={{ position: "relative" }}>
            <div
              style={{
                background: "#27272a",
                color: "white",
                padding: "18px 32px",
                borderRadius: "40px 40px 40px 8px",
                fontSize: 30,
                lineHeight: 1.65,
                fontFamily: FONTS.body,
                whiteSpace: "pre-wrap",
              }}
            >
              {MESSAGE}
            </div>
            <BotTail bgColor={COLORS.bgLight} />
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};
