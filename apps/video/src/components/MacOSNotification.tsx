import type React from "react";
import {
  Img,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { FONTS } from "../constants";

interface MacOSNotificationProps {
  appIcon: string;
  appName: string;
  title: string;
  body: string;
  delay: number;
}

export const MacOSNotification: React.FC<MacOSNotificationProps> = ({
  appIcon,
  appName,
  title,
  body,
  delay,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const progress = spring({
    frame: frame - delay,
    fps,
    config: { damping: 18, stiffness: 120 },
  });

  const x = interpolate(progress, [0, 1], [600, 0]);
  const opacity = interpolate(progress, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });

  return (
    <div
      style={{
        transform: `translateX(${x}px)`,
        opacity,
        display: "flex",
        alignItems: "flex-start",
        gap: 20,
        background: "rgba(30, 30, 32, 0.97)",
        border: "1px solid rgba(255,255,255,0.1)",
        borderRadius: 35,
        padding: "30px 40px 30px 25px",
        width: 860,
      }}
    >
      <Img
        src={staticFile(appIcon)}
        style={{ width: 88, height: 88, borderRadius: 20, flexShrink: 0 }}
      />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            marginBottom: 4,
          }}
        >
          <span
            style={{
              color: "#a1a1aa",
              fontSize: 24,
              fontFamily: FONTS.body,
              fontWeight: 500,
            }}
          >
            {appName}
          </span>
          <span
            style={{
              color: "#71717a",
              fontSize: 20,
              fontFamily: FONTS.body,
            }}
          >
            now
          </span>
        </div>
        <div
          style={{
            color: "white",
            fontSize: 34,
            fontFamily: FONTS.body,
            fontWeight: 700,
            marginBottom: 6,
          }}
        >
          {title}
        </div>
        <div
          style={{
            color: "#a1a1aa",
            fontSize: 26,
            fontFamily: FONTS.body,
            lineHeight: 1.4,
            overflow: "hidden",
            display: "block",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {body}
        </div>
      </div>
    </div>
  );
};
