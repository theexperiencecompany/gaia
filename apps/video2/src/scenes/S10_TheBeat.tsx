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
import { ChatThread } from "../components/ChatThread";

export const S10_TheBeat: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // GAIA final question at frame 60
  const qaP = spring({
    frame: frame - 60,
    fps,
    config: { damping: 200 },
  });
  const qaOpacity = interpolate(qaP, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });
  const qaY = interpolate(qaP, [0, 1], [15, 0]);

  // User "Send it." reply at frame 130
  const replyP = spring({
    frame: frame - 130,
    fps,
    config: { damping: 200 },
  });
  const replyOpacity = interpolate(replyP, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });
  const replyY = interpolate(replyP, [0, 1], [15, 0]);

  // Typing indicator dots at frame 100
  const dot1 = frame >= 100 ? Math.sin((frame - 100) / 8) * 0.5 + 0.5 : 0;
  const dot2 = frame >= 100 ? Math.sin((frame - 100) / 8 + 1.2) * 0.5 + 0.5 : 0;
  const dot3 = frame >= 100 ? Math.sin((frame - 100) / 8 + 2.4) * 0.5 + 0.5 : 0;
  const showTyping = frame >= 100 && frame < 130;

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
      <Sequence from={130}>
        <Audio src={SFX.whip} volume={0.55} />
      </Sequence>

      <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
        <ChatThread
          messages={[
            {
              message: "Looked her up. Found what she cares about.",
              timestamp: "11:58 PM",
              delay: 0,
              showCheckmark: true,
              checkmarkDelay: 5,
            },
            {
              message:
                "Updated your deck. Metrics current, narrative tailored to her thesis.",
              timestamp: "12:20 AM",
              delay: 4,
              showCheckmark: true,
              checkmarkDelay: 9,
            },
            {
              message:
                "Data room cleaned up. Every number she'll dig into is there.",
              timestamp: "1:15 AM",
              delay: 8,
              showCheckmark: true,
              checkmarkDelay: 13,
            },
            {
              message:
                "Created a prep doc with likely questions and talking points.",
              timestamp: "2:30 AM",
              delay: 12,
              showCheckmark: true,
              checkmarkDelay: 17,
            },
            {
              message: "Slacked your co-founder.",
              timestamp: "5:00 AM",
              delay: 16,
              showCheckmark: true,
              checkmarkDelay: 21,
            },
            {
              message:
                "Found 3 open slots. Added a 30-min prep block before each.",
              timestamp: "6:30 AM",
              delay: 20,
              showCheckmark: true,
              checkmarkDelay: 25,
            },
            {
              message:
                "Wrote your reply. Deck, data room, and 3 time slots attached.",
              timestamp: "6:58 AM",
              delay: 24,
              showCheckmark: true,
              checkmarkDelay: 29,
            },
          ]}
        />

        <div style={{ width: 900 }}>
          {/* GAIA final question */}
          <div
            style={{
              transform: `translateY(${qaY}px)`,
              opacity: qaOpacity,
              padding: "0 30px 18px",
              display: "flex",
              alignItems: "flex-end",
              gap: 12,
              marginTop: 16,
            }}
          >
            <div
              style={{
                width: 36,
                height: 36,
                borderRadius: "50%",
                background: COLORS.primary,
                flexShrink: 0,
                marginBottom: 4,
              }}
            />
            <div
              style={{
                background: COLORS.surface,
                borderRadius: "40px 40px 40px 8px",
                padding: "22px 30px",
                fontFamily: FONTS.body,
                fontSize: 28,
                color: COLORS.zinc400,
                lineHeight: 1.45,
              }}
            >
              Ready to send. Want to review first, or just go?
            </div>
          </div>

          {/* Typing indicator */}
          {showTyping && (
            <div
              style={{
                padding: "0 30px 18px",
                display: "flex",
                justifyContent: "flex-end",
              }}
            >
              <div
                style={{
                  background: COLORS.primary,
                  borderRadius: "40px 40px 8px 40px",
                  padding: "18px 24px",
                  display: "flex",
                  gap: 8,
                  alignItems: "center",
                }}
              >
                {[dot1, dot2, dot3].map((d, i) => (
                  <div
                    key={i}
                    style={{
                      width: 10,
                      height: 10,
                      borderRadius: "50%",
                      background: "#000",
                      opacity: d,
                    }}
                  />
                ))}
              </div>
            </div>
          )}

          {/* User "Send it." reply */}
          <div
            style={{
              transform: `translateY(${replyY}px)`,
              opacity: replyOpacity,
              padding: "0 30px 18px",
              display: "flex",
              justifyContent: "flex-end",
            }}
          >
            <div
              style={{
                background: COLORS.primary,
                borderRadius: "40px 40px 8px 40px",
                padding: "22px 36px",
                fontFamily: FONTS.body,
                fontSize: 32,
                fontWeight: 700,
                color: "#000",
              }}
            >
              Send it.
            </div>
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};
