import React from "react";
import {
  AbsoluteFill,
  Img,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { COLORS, FONTS } from "../constants";

// Pill chip matching HeroUI Chip — no border, flat
const Chip: React.FC<{
  children: React.ReactNode;
  color?: "success" | "default";
  radius?: "sm" | "full";
}> = ({ children, color = "default", radius = "sm" }) => {
  const bg =
    color === "success" ? "rgba(34,197,94,0.15)" : "rgba(63,63,70,0.5)";
  const textColor = color === "success" ? "#22c55e" : "#a1a1aa";
  const br = radius === "full" ? 1000 : 6;
  return (
    <span
      style={{
        background: bg,
        color: textColor,
        borderRadius: br,
        padding: "3px 10px",
        fontFamily: FONTS.body,
        fontSize: 13,
        fontWeight: 400,
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        whiteSpace: "nowrap",
      }}
    >
      {children}
    </span>
  );
};

// Tool chip — flat, no border, radius full
const ToolChip: React.FC<{ label: string; delay: number }> = ({
  label,
  delay,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = spring({ frame: frame - delay, fps, config: { damping: 200 } });
  const opacity = interpolate(p, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });
  const scale = interpolate(p, [0, 0.6, 1], [0.85, 1.05, 1.0]);
  return (
    <span
      style={{
        opacity,
        transform: `scale(${scale})`,
        background: "rgba(63,63,70,0.45)",
        color: "#d4d4d8",
        borderRadius: 1000,
        padding: "6px 16px",
        fontFamily: FONTS.body,
        fontSize: 15,
        fontWeight: 300,
        display: "inline-flex",
        alignItems: "center",
        whiteSpace: "nowrap",
      }}
    >
      {label}
    </span>
  );
};

// Button group button matching HeroUI flat variant — height 44px, fontSize 15
const FlatButton: React.FC<{
  icon: React.ReactNode;
  label?: string;
  color: "danger" | "primary" | "warning" | "default";
  delay: number;
  pressed?: boolean;
  framePressed?: number;
}> = ({ icon, label, color, delay, pressed, framePressed }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = spring({ frame: frame - delay, fps, config: { damping: 200 } });
  const opacity = interpolate(p, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });

  const colors = {
    danger: { bg: "rgba(239,68,68,0.12)", text: "#f87171" },
    primary: { bg: "rgba(0,187,255,0.12)", text: "#00bbff" },
    warning: { bg: "rgba(245,158,11,0.12)", text: "#f59e0b" },
    default: { bg: "rgba(63,63,70,0.4)", text: "#a1a1aa" },
  };

  // Press animation
  const pressP =
    pressed && framePressed !== undefined
      ? spring({
          frame: frame - framePressed,
          fps,
          config: { damping: 8, stiffness: 400 },
        })
      : 0;
  const btnScale =
    pressed && framePressed !== undefined
      ? interpolate(pressP, [0, 0.2, 0.5, 1], [1, 0.91, 1.04, 1.0])
      : 1;

  return (
    <div
      style={{
        flex: 1,
        height: 44,
        background: colors[color].bg,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        gap: 7,
        opacity,
        transform: `scale(${btnScale})`,
        cursor: "pointer",
      }}
    >
      <span style={{ color: colors[color].text, display: "flex" }}>{icon}</span>
      {label && (
        <span
          style={{
            fontFamily: FONTS.body,
            fontSize: 15,
            fontWeight: 500,
            color: colors[color].text,
          }}
        >
          {label}
        </span>
      )}
    </div>
  );
};

// SVG icons matching actual app (@icons / Hugeicons)
const UnlinkIcon = () => (
  <svg
    width={16}
    height={16}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth={1.5}
    strokeLinecap="round"
  >
    <path d="M9 7H7a5 5 0 000 10h2M15 7h2a5 5 0 010 10h-2M9 12h6M3 3l18 18" />
  </svg>
);

const GlobalIcon = () => (
  <svg
    width={16}
    height={16}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth={1.5}
    strokeLinecap="round"
  >
    <circle cx={12} cy={12} r={9} />
    <path d="M2 12h20M12 2c-3 3-4.5 6-4.5 10s1.5 7 4.5 10M12 2c3 3 4.5 6 4.5 10S15 19 12 22" />
  </svg>
);

const LinkSquareIcon = () => (
  <svg
    width={16}
    height={16}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth={1.5}
    strokeLinecap="round"
  >
    <path d="M10 14a4 4 0 005.66 0l3-3a4 4 0 00-5.66-5.66l-1.5 1.5M14 10a4 4 0 00-5.66 0l-3 3a4 4 0 005.66 5.66l1.5-1.5" />
    <path d="M18 3h3v3M21 3l-7 7" />
  </svg>
);

const ShareIcon = () => (
  <svg
    width={16}
    height={16}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth={1.5}
    strokeLinecap="round"
  >
    <circle cx={18} cy={5} r={2} />
    <circle cx={6} cy={12} r={2} />
    <circle cx={18} cy={19} r={2} />
    <path d="M8 12h8M8.5 6.5l7-3M8.5 17.5l7 3" />
  </svg>
);

const RemoveCircleIcon = () => (
  <svg
    width={16}
    height={16}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth={1.5}
    strokeLinecap="round"
  >
    <circle cx={12} cy={12} r={9} />
    <path d="M9 12h6" />
  </svg>
);

const TOOLS = ["Read Page", "Create Page", "Query Database", "Update Block"];

// PUBLISH_FRAME — the frame at which Publish button gets pressed
const PUBLISH_FRAME = 62;

export const S26b_IntegrationPublish: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // After publish, show the "published" button set — longer dwell before switching
  const isPublished = frame >= PUBLISH_FRAME + 35;

  // App background (integrations page content)
  const bgP = spring({ frame, fps, config: { damping: 200 } });
  const bgOpacity = interpolate(bgP, [0, 0.2], [0, 1], {
    extrapolateRight: "clamp",
  });

  // Sidebar slides in from right
  const sidebarP = spring({
    frame: frame - 5,
    fps,
    config: { damping: 22, stiffness: 100 },
  });
  const sidebarX = interpolate(sidebarP, [0, 1], [600, 0]);
  const sidebarOpacity = interpolate(sidebarP, [0, 0.15], [0, 1], {
    extrapolateRight: "clamp",
  });

  // Sidebar header elements stagger in
  const iconP = spring({ frame: frame - 18, fps, config: { damping: 200 } });
  const chipsP = spring({ frame: frame - 24, fps, config: { damping: 200 } });
  const nameP = spring({ frame: frame - 30, fps, config: { damping: 200 } });
  const descP = spring({ frame: frame - 36, fps, config: { damping: 200 } });

  const itemOpacity = (p: number) =>
    interpolate(p, [0, 0.1], [0, 1], { extrapolateRight: "clamp" });
  const itemY = (p: number) => interpolate(p, [0, 1], [10, 0]);

  // Published state transition
  const publishedP = spring({
    frame: frame - PUBLISH_FRAME - 10,
    fps,
    config: { damping: 200 },
  });
  const publishedOpacity = interpolate(publishedP, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill style={{ background: COLORS.bg }}>
      {/* Main content area — dimmed app background */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          opacity: bgOpacity * 0.4,
          background: COLORS.bg,
          display: "flex",
          alignItems: "center",
          justifyContent: "flex-start",
          paddingLeft: 80,
        }}
      >
        {/* Fake integrations list rows (blurred, background context) */}
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 4,
            width: 480,
            filter: "blur(1px)",
          }}
        >
          {["Gmail", "Google Calendar", "GitHub", "Slack", "Notion"].map(
            (name, i) => (
              <div
                key={name}
                style={{
                  height: 60,
                  borderRadius: 16,
                  background:
                    name === "Notion"
                      ? "rgba(39,39,42,0.6)"
                      : "transparent",
                  display: "flex",
                  alignItems: "center",
                  paddingLeft: 16,
                  gap: 14,
                  opacity: 0.6 + (i === 4 ? 0.4 : 0),
                }}
              >
                <div
                  style={{
                    width: 32,
                    height: 32,
                    borderRadius: 8,
                    background: "#27272a",
                  }}
                />
                <div>
                  <div
                    style={{
                      fontFamily: FONTS.body,
                      fontSize: 14,
                      fontWeight: 500,
                      color: "#f4f4f5",
                    }}
                  >
                    {name}
                  </div>
                  <div
                    style={{
                      fontFamily: FONTS.body,
                      fontSize: 12,
                      color: "#71717a",
                    }}
                  >
                    {name === "Notion" ? "Connected" : "Connected"}
                  </div>
                </div>
              </div>
            )
          )}
        </div>
      </div>

      {/* Right sidebar — IntegrationSidebar, width 560 */}
      <div
        style={{
          position: "absolute",
          top: 0,
          right: 0,
          width: 560,
          height: "100%",
          background: "#18181b",
          borderLeft: "1px solid rgba(255,255,255,0.06)",
          transform: `translateX(${sidebarX}px)`,
          opacity: sidebarOpacity,
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
        }}
      >
        {/* Header section with larger padding */}
        <div
          style={{
            padding: "32px 28px 20px",
            display: "flex",
            flexDirection: "column",
            gap: 14,
          }}
        >
          {/* Integration icon — 52x52 container, 36x36 icon */}
          <div
            style={{
              opacity: itemOpacity(iconP),
              transform: `translateY(${itemY(iconP)}px)`,
            }}
          >
            <div
              style={{
                width: 52,
                height: 52,
                borderRadius: 12,
                background: "#27272a",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                overflow: "hidden",
              }}
            >
              <Img
                src={staticFile("images/icons/notion.webp")}
                style={{ width: 36, height: 36, objectFit: "contain" }}
              />
            </div>
          </div>

          {/* Chips row */}
          <div
            style={{
              opacity: itemOpacity(chipsP),
              transform: `translateY(${itemY(chipsP)}px)`,
              display: "flex",
              gap: 6,
              flexWrap: "wrap",
            }}
          >
            <Chip color="success">Connected</Chip>
            <Chip color="default">
              {/* Avatar dot */}
              <span
                style={{
                  width: 14,
                  height: 14,
                  borderRadius: "50%",
                  background: "#00bbff",
                  display: "inline-block",
                  flexShrink: 0,
                }}
              />
              Created by You
            </Chip>
          </div>

          {/* Name — 28px */}
          <div
            style={{
              opacity: itemOpacity(nameP),
              transform: `translateY(${itemY(nameP)}px)`,
            }}
          >
            <h1
              style={{
                fontFamily: FONTS.body,
                fontSize: 28,
                fontWeight: 600,
                color: "#f4f4f5",
                margin: 0,
                lineHeight: 1.2,
              }}
            >
              Notion
            </h1>
          </div>

          {/* Description — 16px */}
          <div
            style={{
              opacity: itemOpacity(descP),
              transform: `translateY(${itemY(descP)}px)`,
            }}
          >
            <p
              style={{
                fontFamily: FONTS.body,
                fontSize: 16,
                fontWeight: 300,
                color: "#a1a1aa",
                margin: 0,
                lineHeight: 1.55,
              }}
            >
              Read and write pages, databases, and blocks
            </p>
          </div>

          {/* Button group — BEFORE publish — no border wrapper, flat */}
          {!isPublished && (
            <div
              style={{
                overflow: "hidden",
                borderRadius: 10,
                display: "flex",
              }}
            >
              <FlatButton
                icon={<UnlinkIcon />}
                label="Disconnect"
                color="danger"
                delay={44}
              />
              <div style={{ width: 1, background: "rgba(255,255,255,0.07)" }} />
              <FlatButton
                icon={<GlobalIcon />}
                label="Publish"
                color="primary"
                delay={50}
                pressed={frame >= PUBLISH_FRAME}
                framePressed={PUBLISH_FRAME}
              />
            </div>
          )}

          {/* Button group — AFTER publish (View + Unpublish + Share) — no border wrapper */}
          {isPublished && (
            <div
              style={{
                overflow: "hidden",
                borderRadius: 10,
                display: "flex",
                opacity: publishedOpacity,
              }}
            >
              <FlatButton
                icon={<UnlinkIcon />}
                label="Disconnect"
                color="danger"
                delay={0}
              />
              <div style={{ width: 1, background: "rgba(255,255,255,0.07)" }} />
              <FlatButton
                icon={<LinkSquareIcon />}
                label="View"
                color="primary"
                delay={0}
              />
              <div style={{ width: 1, background: "rgba(255,255,255,0.07)" }} />
              <FlatButton
                icon={<RemoveCircleIcon />}
                color="warning"
                delay={0}
              />
              <div style={{ width: 1, background: "rgba(255,255,255,0.07)" }} />
              <FlatButton icon={<ShareIcon />} color="default" delay={0} />
            </div>
          )}

          {/* "Published to marketplace" success banner */}
          {isPublished && (
            <div
              style={{
                opacity: publishedOpacity,
                background: "rgba(34,197,94,0.1)",
                border: "1px solid rgba(34,197,94,0.2)",
                borderRadius: 10,
                padding: "12px 16px",
                display: "flex",
                alignItems: "center",
                gap: 8,
              }}
            >
              <svg
                width={16}
                height={16}
                viewBox="0 0 24 24"
                fill="none"
                stroke="#22c55e"
                strokeWidth={2}
                strokeLinecap="round"
              >
                <circle cx={12} cy={12} r={9} />
                <path d="M9 12l2 2 4-4" />
              </svg>
              <span
                style={{
                  fontFamily: FONTS.body,
                  fontSize: 14,
                  color: "#22c55e",
                  fontWeight: 500,
                }}
              >
                Published to marketplace
              </span>
            </div>
          )}

          {/* Tools header — 14px label */}
          <div
            style={{
              opacity: itemOpacity(descP),
              fontFamily: FONTS.body,
              fontSize: 14,
              fontWeight: 500,
              color: "#71717a",
              textTransform: "uppercase",
              letterSpacing: 0.8,
              marginTop: 4,
            }}
          >
            Available Tools ({TOOLS.length})
          </div>
        </div>

        {/* Tools chips — SidebarContent (flex-1 overflow-y-auto) */}
        <div
          style={{ flex: 1, padding: "0 28px 24px", overflowY: "hidden" }}
        >
          <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
            {TOOLS.map((tool, i) => (
              <ToolChip key={tool} label={tool} delay={58 + i * 8} />
            ))}
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};
