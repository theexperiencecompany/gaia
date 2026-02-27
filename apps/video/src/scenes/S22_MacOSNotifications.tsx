import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig, spring, interpolate } from "remotion";
import { COLORS, FONTS } from "../constants";
import { MacOSNotification } from "../components/MacOSNotification";

const NOTIFICATIONS = [
  {
    appIcon: "images/icons/macos/telegram.webp",
    appName: "Telegram",
    title: "Daily Email Digest",
    body: "12 emails summarized. Key: Sarah's Q4 report needs reply. Meeting at 2 PM confirmed.",
    delay: 0,
  },
  {
    appIcon: "images/icons/macos/slack.webp",
    appName: "Slack",
    title: "Workflow Complete",
    body: "Posted to #daily-briefing. 4 tools used in 3.2s.",
    delay: 10,
  },
  {
    appIcon: "images/icons/macos/discord.webp",
    appName: "Discord",
    title: "GAIA",
    body: "Your morning briefing is ready. Tap to view.",
    delay: 20,
  },
];

export const S22_MacOSNotifications: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // "Your output, everywhere you are." text
  const labelProgress = spring({ frame: frame - 30, fps, config: { damping: 200 } });
  const labelOpacity = interpolate(labelProgress, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });

  return (
    <AbsoluteFill
      style={{
        background: COLORS.bgLight,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      {/* "Your output, everywhere you are." — top center */}
      <div
        style={{
          position: "absolute",
          top: 80,
          left: "50%",
          transform: "translateX(-50%)",
          whiteSpace: "nowrap",
          fontFamily: FONTS.body,
          fontSize: 68,
          fontWeight: 700,
          color: COLORS.textDark,
          opacity: labelOpacity,
        }}
      >
        Your output, everywhere you are.
      </div>

      {/* Notifications stack — centered on screen */}
      <div
        style={{
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
    </AbsoluteFill>
  );
};
