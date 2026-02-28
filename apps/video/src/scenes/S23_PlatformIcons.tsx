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
import { MacOSNotification } from "../components/MacOSNotification";
import { PlatformIcon } from "../components/PlatformIcon";
import { COLORS, FONTS } from "../constants";
import { SFX } from "../sfx";

const PLATFORMS = [
  {
    src: "images/icons/macos/telegram.webp",
    label: "Telegram",
    delay: 0,
    comingSoon: false,
  },
  {
    src: "images/icons/macos/discord.webp",
    label: "Discord",
    delay: 8,
    comingSoon: false,
  },
  {
    src: "images/icons/macos/slack.webp",
    label: "Slack",
    delay: 16,
    comingSoon: false,
  },
  {
    src: "images/icons/macos/whatsapp.webp",
    label: "WhatsApp",
    delay: 24,
    comingSoon: false,
  },
  {
    src: "images/icons/macos/imessage.webp",
    label: "iMessage",
    delay: 32,
    comingSoon: false,
  },
];

const NOTIFICATIONS = [
  {
    appIcon: "images/icons/macos/telegram.webp",
    appName: "Telegram",
    title: "Daily Email Digest",
    body: "12 emails summarized. Key: Sarah's Q4 report needs reply. Meeting at 2 PM confirmed.",
    delay: 72,
  },
  {
    appIcon: "images/icons/macos/slack.webp",
    appName: "Slack",
    title: "Workflow Complete",
    body: "Posted to #daily-briefing. 4 tools used in 3.2s.",
    delay: 82,
  },
  {
    appIcon: "images/icons/macos/discord.webp",
    appName: "Discord",
    title: "GAIA",
    body: "Your morning briefing is ready. Tap to view.",
    delay: 92,
  },
];

export const S23_PlatformIcons: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Phase 1 headline: "GAIA meets you where you are." — appears at frame 60
  const headline1Progress = spring({
    frame: frame - 60,
    fps,
    config: { damping: 15 },
  });
  const headline1Blur = interpolate(headline1Progress, [0, 1], [20, 0]);
  const headline1Scale = interpolate(headline1Progress, [0, 1], [0.95, 1.0]);
  // Fade out headline 1 between frames 70–80
  const headline1FadeOut = interpolate(frame, [70, 80], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const headline1Opacity = interpolate(
    headline1Progress,
    [0, 0.1],
    [0, 1],
    { extrapolateRight: "clamp" }
  ) * headline1FadeOut;

  // Phase 2 headline: "Notifications, wherever you want." — fades in frames 70–80
  const headline2Opacity = interpolate(frame, [70, 80], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const headline2Progress = spring({
    frame: frame - 70,
    fps,
    config: { damping: 15 },
  });
  const headline2Blur = interpolate(headline2Progress, [0, 1], [20, 0]);
  const headline2Scale = interpolate(headline2Progress, [0, 1], [0.95, 1.0]);

  // Platform icons: shift upward once notifications phase begins
  const iconsShiftProgress = spring({
    frame: frame - 70,
    fps,
    config: { damping: 18, stiffness: 120 },
  });
  const iconsTopOffset = interpolate(iconsShiftProgress, [0, 1], [0, -190]);

  return (
    <AbsoluteFill
      style={{
        background: COLORS.bgLight,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      {/* Platform icon audio cues */}
      {PLATFORMS.map((p) => (
        <Sequence key={p.label} from={p.delay}>
          <Audio src={SFX.uiSwitch} volume={0.2} />
        </Sequence>
      ))}

      {/* Phase 1 headline whoosh */}
      <Sequence from={60}>
        <Audio src={SFX.whoosh} volume={0.3} />
      </Sequence>

      {/* Phase 2 transition whoosh */}
      <Sequence from={70}>
        <Audio src={SFX.whoosh} volume={0.35} />
      </Sequence>

      {/* Notification ding audio cues */}
      {NOTIFICATIONS.map((notif, i) => (
        <Sequence key={`notif-sfx-${i}`} from={notif.delay}>
          <Audio src={SFX.uiSwitch} volume={0.55} />
        </Sequence>
      ))}

      {/* Platform icons — upper portion, shift up when notifications appear */}
      <div
        style={{
          position: "absolute",
          top: "50%",
          left: "50%",
          transform: `translate(-50%, calc(-50% - 100px + ${iconsTopOffset}px))`,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 40,
        }}
      >
        {/* Headline layer — both headlines occupy same space via absolute overlay */}
        <div style={{ position: "relative", height: 100, width: 1100 }}>
          {/* Headline 1 */}
          {frame >= 60 && (
            <div
              style={{
                position: "absolute",
                inset: 0,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontFamily: FONTS.display,
                textTransform: "uppercase" as const,
                fontSize: 72,
                fontWeight: 700,
                color: COLORS.textDark,
                textAlign: "center",
                filter: `blur(${headline1Blur}px)`,
                transform: `scale(${headline1Scale})`,
                opacity: headline1Opacity,
                whiteSpace: "nowrap",
              }}
            >
              GAIA meets you where you are.
            </div>
          )}

          {/* Headline 2 */}
          {frame >= 70 && (
            <div
              style={{
                position: "absolute",
                inset: 0,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontFamily: FONTS.display,
                textTransform: "uppercase" as const,
                fontSize: 72,
                fontWeight: 700,
                color: COLORS.textDark,
                textAlign: "center",
                filter: `blur(${headline2Blur}px)`,
                transform: `scale(${headline2Scale})`,
                opacity: headline2Opacity,
                whiteSpace: "nowrap",
              }}
            >
              Notifications, wherever you want.
            </div>
          )}
        </div>

        {/* Icons row */}
        <div
          style={{
            display: "flex",
            alignItems: "flex-end",
            gap: 44,
          }}
        >
          {PLATFORMS.map((platform, i) => (
            <PlatformIcon
              key={i}
              src={platform.src}
              label={platform.label}
              delay={platform.delay}
              size={150}
              iconIndex={i}
              comingSoon={platform.comingSoon}
              textColor={COLORS.textDark}
            />
          ))}
        </div>
      </div>

      {/* Notifications stack — centered lower portion, slides in during phase 2 */}
      {frame >= 70 && (
        <div
          style={{
            position: "absolute",
            bottom: 80,
            left: "50%",
            transform: "translateX(-50%)",
            display: "flex",
            flexDirection: "column",
            gap: 20,
            alignItems: "center",
          }}
        >
          {NOTIFICATIONS.map((notif, i) => (
            <MacOSNotification
              key={i}
              appIcon={notif.appIcon}
              appName={notif.appName}
              title={notif.title}
              body={notif.body}
              delay={notif.delay}
            />
          ))}
        </div>
      )}
    </AbsoluteFill>
  );
};
