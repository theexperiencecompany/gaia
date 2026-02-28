import React from "react";
import { AbsoluteFill, Audio, Sequence, useCurrentFrame, useVideoConfig, spring, interpolate, Img, staticFile } from "remotion";
import { COLORS, FONTS } from "../constants";
import { SceneBackground } from "../components/SceneBackground";
import { SFX } from "../sfx";
import { BotTail } from "./S06_UserChat";
import { CalendarUpload01Icon, InboxUnreadIcon, Clock01Icon } from "@theexperiencecompany/gaia-icons/solid-rounded";

const FULL_MESSAGE = `Your Daily Digest is ready.

→ Design review at 2 PM
→ Sarah Q4 — reply needed
→ Follow up on vendor invoice

Posted to Slack. Todos updated.`;

const CHARS_PER_FRAME = 3;
const TEXT_DONE_FRAME = Math.ceil(FULL_MESSAGE.length / CHARS_PER_FRAME);
const CHIP_DELAY_1 = TEXT_DONE_FRAME + 8;
const CHIP_DELAY_2 = TEXT_DONE_FRAME + 18;
const CHIP_DELAY_3 = TEXT_DONE_FRAME + 28;

const CHIP_STYLE: React.CSSProperties = {
  background: "#27272a",
  borderRadius: 40,
  padding: "10px 24px",
  display: "flex",
  alignItems: "center",
  gap: 10,
  color: "#e4e4e7",
  fontSize: 26,
  fontFamily: FONTS.body,
  fontWeight: 500,
};

interface ActionChipProps {
  frame: number;
  fps: number;
  delay: number;
  icon: React.ReactNode;
  label: string;
}

const ActionChip: React.FC<ActionChipProps> = ({ frame, fps, delay, icon, label }) => {
  const p = spring({ frame: frame - delay, fps, config: { damping: 12, stiffness: 200 } });
  const scale = interpolate(p, [0, 0.5, 1], [0, 1.1, 1.0]);
  const opacity = interpolate(p, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });

  return (
    <div
      style={{
        ...CHIP_STYLE,
        transform: `scale(${scale})`,
        opacity,
      }}
    >
      {icon}
      {label}
    </div>
  );
};

export const S19_BotMessageStream: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Stream chars at CHARS_PER_FRAME per frame
  const charIndex = Math.min(Math.floor(frame * CHARS_PER_FRAME), FULL_MESSAGE.length);
  const displayText = FULL_MESSAGE.slice(0, charIndex);
  const cursorOpacity = Math.floor(frame / 10) % 2 === 0 ? 1 : 0;

  // Bubble entrance
  const enterProgress = spring({ frame, fps, config: { damping: 25 } });
  const enterY = interpolate(enterProgress, [0, 1], [30, 0]);
  const enterOpacity = interpolate(enterProgress, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });

  // Chip row wrapper fades in when first chip appears
  const chipRowP = spring({ frame: frame - CHIP_DELAY_1, fps, config: { damping: 12, stiffness: 200 } });
  const chipRowOpacity = interpolate(chipRowP, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });

  return (
    <AbsoluteFill>
      {/* Action chip pops */}
      <Sequence from={CHIP_DELAY_1}><Audio src={SFX.whip} volume={0.4} /></Sequence>
      <Sequence from={CHIP_DELAY_2}><Audio src={SFX.whip} volume={0.4} /></Sequence>
      <Sequence from={CHIP_DELAY_3}><Audio src={SFX.whip} volume={0.4} /></Sequence>
      <SceneBackground variant="light" />
      <div
        style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <div style={{ width: 1400, display: "flex", flexDirection: "column", gap: 28 }}>
          {/* GAIA bot message */}
          <div
            style={{
              display: "flex",
              alignItems: "flex-start",
              gap: 20,
              paddingLeft: 8,
              transform: `translateY(${enterY}px)`,
              opacity: enterOpacity,
            }}
          >
            <Img
              src={staticFile("images/logos/logo.webp")}
              style={{ width: 60, height: 60, borderRadius: "50%", objectFit: "contain", flexShrink: 0, marginTop: 4 }}
            />
            <div style={{ position: "relative" }}>
              <div
                style={{
                  background: "#27272a",
                  color: "white",
                  padding: "18px 32px",
                  borderRadius: 28,
                  fontSize: 30,
                  lineHeight: 1.65,
                  fontFamily: FONTS.body,
                  whiteSpace: "pre-wrap",
                  maxWidth: 1100,
                }}
              >
                {displayText}
                <span
                  style={{
                    display: "inline-block",
                    width: 2,
                    height: "1em",
                    background: COLORS.primary,
                    marginLeft: 3,
                    verticalAlign: "text-bottom",
                    opacity: charIndex < FULL_MESSAGE.length ? cursorOpacity : 0,
                  }}
                />
              </div>
              <BotTail bgColor={COLORS.bgLight} />
            </div>
          </div>

          {/* Action chips row — left-aligned under the bubble, not the avatar */}
          <div
            style={{
              paddingLeft: 80,
              opacity: chipRowOpacity,
            }}
          >
            <div style={{ display: "flex", flexDirection: "row", gap: 12 }}>
              <ActionChip
                frame={frame}
                fps={fps}
                delay={CHIP_DELAY_1}
                icon={<CalendarUpload01Icon size={22} style={{ color: "#60a5fa" }} />}
                label="Add design review to calendar"
              />
              <ActionChip
                frame={frame}
                fps={fps}
                delay={CHIP_DELAY_2}
                icon={<InboxUnreadIcon size={22} style={{ color: "#38bdf8" }} />}
                label="Reply to Sarah"
              />
              <ActionChip
                frame={frame}
                fps={fps}
                delay={CHIP_DELAY_3}
                icon={<Clock01Icon size={22} style={{ color: "#f59e0b" }} />}
                label="Snooze invoice reminder"
              />
            </div>
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};
