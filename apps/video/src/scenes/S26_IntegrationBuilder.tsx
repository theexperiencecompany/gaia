import {
  CheckmarkCircle02Icon,
  GlobalIcon,
  LinkSquareIcon,
  RemoveCircleIcon,
  Share08Icon,
  Unlink04Icon,
} from "@theexperiencecompany/gaia-icons/solid-rounded";
import {
  KeyIcon,
  LinkIcon,
  McpServerIcon,
} from "@theexperiencecompany/gaia-icons/stroke-rounded";
import type React from "react";
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

// ─── Form sub-components ──────────────────────────────────────────────────────

const Field: React.FC<{
  label: string;
  value: string;
  placeholder: string;
  delay: number;
  icon?: React.ReactNode;
  type?: "text" | "password";
}> = ({ label, value, placeholder, delay, icon, type }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = spring({ frame: frame - delay, fps, config: { damping: 200 } });
  const opacity = interpolate(p, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });
  const y = interpolate(p, [0, 1], [12, 0]);
  const charIndex = Math.min(
    Math.max(0, Math.floor((frame - delay - 8) * 5)),
    value.length,
  );
  const displayValue = value.slice(0, charIndex);

  return (
    <div
      style={{
        opacity,
        transform: `translateY(${y}px)`,
        display: "flex",
        flexDirection: "column",
        gap: 10,
      }}
    >
      <span
        style={{
          fontFamily: FONTS.body,
          fontSize: 22,
          color: "#a1a1aa",
          paddingLeft: 4,
        }}
      >
        {label}
      </span>
      <div
        style={{
          background: "#27272a",
          borderRadius: 16,
          height: 76,
          display: "flex",
          alignItems: "center",
          paddingLeft: 22,
          paddingRight: 22,
          gap: 14,
        }}
      >
        {icon && (
          <span
            style={{
              color: "#71717a",
              flexShrink: 0,
              display: "flex",
              alignItems: "center",
            }}
          >
            {icon}
          </span>
        )}
        <span
          style={{
            fontFamily: FONTS.body,
            fontSize: 22,
            color: displayValue ? "#f4f4f5" : "#52525b",
          }}
        >
          {type === "password" && displayValue
            ? "•".repeat(Math.min(displayValue.length, 24))
            : displayValue || placeholder}
        </span>
      </div>
    </div>
  );
};

const TextareaField: React.FC<{
  label: string;
  value: string;
  placeholder: string;
  delay: number;
}> = ({ label, value, placeholder, delay }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = spring({ frame: frame - delay, fps, config: { damping: 200 } });
  const opacity = interpolate(p, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });
  const y = interpolate(p, [0, 1], [12, 0]);
  const charIndex = Math.min(
    Math.max(0, Math.floor((frame - delay - 8) * 4)),
    value.length,
  );
  const displayValue = value.slice(0, charIndex);

  return (
    <div
      style={{
        opacity,
        transform: `translateY(${y}px)`,
        display: "flex",
        flexDirection: "column",
        gap: 10,
      }}
    >
      <span
        style={{
          fontFamily: FONTS.body,
          fontSize: 22,
          color: "#a1a1aa",
          paddingLeft: 4,
        }}
      >
        {label}
      </span>
      <div
        style={{
          background: "#27272a",
          borderRadius: 16,
          minHeight: 100,
          padding: "20px 22px",
          display: "flex",
          alignItems: "flex-start",
        }}
      >
        <span
          style={{
            fontFamily: FONTS.body,
            fontSize: 22,
            color: displayValue ? "#f4f4f5" : "#52525b",
            lineHeight: 1.55,
          }}
        >
          {displayValue || placeholder}
        </span>
      </div>
    </div>
  );
};

// ─── Sidebar sub-components ───────────────────────────────────────────────────

const SidebarChip: React.FC<{
  color: "success" | "default";
  children: React.ReactNode;
  startContent?: React.ReactNode;
}> = ({ color, children, startContent }) => {
  const bg =
    color === "success" ? "rgba(34,197,94,0.15)" : "rgba(63,63,70,0.45)";
  const textColor = color === "success" ? "#22c55e" : "#a1a1aa";
  return (
    <span
      style={{
        background: bg,
        color: textColor,
        borderRadius: 8,
        padding: "8px 16px",
        fontFamily: FONTS.body,
        fontSize: 22,
        fontWeight: 400,
        display: "inline-flex",
        alignItems: "center",
        gap: 8,
        whiteSpace: "nowrap",
      }}
    >
      {startContent}
      {children}
    </span>
  );
};

// Full-text flat button (2-button pre-publish state)
const FlatBtn: React.FC<{
  icon: React.ReactNode;
  label: string;
  color: "danger" | "primary";
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
    danger: { bg: "rgba(239,68,68,0.15)", text: "#f87171" },
    primary: { bg: "rgba(0,187,255,0.15)", text: "#00bbff" },
  };
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
        height: 68,
        background: colors[color].bg,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        gap: 10,
        opacity,
        transform: `scale(${btnScale})`,
      }}
    >
      <span
        style={{
          color: colors[color].text,
          display: "flex",
          alignItems: "center",
        }}
      >
        {icon}
      </span>
      <span
        style={{
          fontFamily: FONTS.body,
          fontSize: 22,
          fontWeight: 500,
          color: colors[color].text,
        }}
      >
        {label}
      </span>
    </div>
  );
};

// Icon-only flat button (4-button post-publish state)
const IconBtn: React.FC<{
  icon: React.ReactNode;
  color: "danger" | "primary" | "warning" | "default";
  opacity: number;
}> = ({ icon, color, opacity }) => {
  const colors = {
    danger: { bg: "rgba(239,68,68,0.15)", text: "#f87171" },
    primary: { bg: "rgba(0,187,255,0.15)", text: "#00bbff" },
    warning: { bg: "rgba(245,158,11,0.15)", text: "#f59e0b" },
    default: { bg: "rgba(63,63,70,0.4)", text: "#a1a1aa" },
  };
  return (
    <div
      style={{
        flex: 1,
        height: 68,
        background: colors[color].bg,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        opacity,
      }}
    >
      <span
        style={{
          color: colors[color].text,
          display: "flex",
          alignItems: "center",
        }}
      >
        {icon}
      </span>
    </div>
  );
};

// Tool chip — bordered radius="full" font-light text-zinc-300
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
        border: "1px solid #3f3f46",
        borderRadius: 1000,
        padding: "10px 24px",
        fontFamily: FONTS.body,
        fontSize: 22,
        fontWeight: 300,
        color: "#d4d4d8",
        display: "inline-flex",
        alignItems: "center",
        whiteSpace: "nowrap",
        background: "transparent",
      }}
    >
      {label}
    </span>
  );
};

// ─── Timing constants ─────────────────────────────────────────────────────────

const CREATE_FRAME = 88; // Create integration button press
const SIDEBAR_START = CREATE_FRAME + 14; // Sidebar phase begins (isCreated gate)
const CHIP_DELAY = CREATE_FRAME + 20;
const TITLE_DELAY = CREATE_FRAME + 26;
const DESC_DELAY = CREATE_FRAME + 30;
const BTNS_DELAY = CREATE_FRAME + 36;
const TOOLS_DELAY = CREATE_FRAME + 44; // Tools header
// Last tool chip: TOOLS_DELAY + 8 + 3*7 = CREATE_FRAME + 73 = 161
const PUBLISH_FRAME = 175; // Publish button press — after all chips settled
const PUBLISHED_GATE = PUBLISH_FRAME + 20; // Switch to published button group + banner

const TOOLS = ["Read Page", "Create Page", "Query Database", "Update Block"];

// ─── Main component ───────────────────────────────────────────────────────────

export const S26_IntegrationBuilder: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const overlayP = spring({ frame, fps, config: { damping: 200 } });
  const overlayOpacity = interpolate(overlayP, [0, 0.3], [0, 1], {
    extrapolateRight: "clamp",
  });

  const modalP = spring({
    frame: frame - 5,
    fps,
    config: { damping: 22, stiffness: 120 },
  });
  const modalScale = interpolate(modalP, [0, 0.5, 1], [0.92, 1.02, 1.0]);
  const modalOpacity = interpolate(modalP, [0, 0.15], [0, 1], {
    extrapolateRight: "clamp",
  });

  const headerP = spring({ frame: frame - 10, fps, config: { damping: 200 } });
  const headerOpacity = interpolate(headerP, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });

  const btnAppearP = spring({
    frame: frame - 78,
    fps,
    config: { damping: 200 },
  });
  const btnAppearOpacity = interpolate(btnAppearP, [0, 0.1], [0, 1], {
    extrapolateRight: "clamp",
  });

  // Create button press
  const createPressP = spring({
    frame: frame - CREATE_FRAME,
    fps,
    config: { damping: 8, stiffness: 400 },
  });
  const createBtnScale = interpolate(
    createPressP,
    [0, 0.2, 0.6, 1],
    [1.0, 0.92, 1.06, 1.0],
  );

  // Form fades out
  const formOpacity = interpolate(
    frame,
    [CREATE_FRAME + 4, CREATE_FRAME + 18],
    [1, 0],
    {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    },
  );

  // Sidebar springs in
  const sidebarP = spring({
    frame: frame - SIDEBAR_START,
    fps,
    config: { damping: 22, stiffness: 110 },
  });
  const sidebarOpacity = interpolate(sidebarP, [0, 0.15], [0, 1], {
    extrapolateRight: "clamp",
  });
  const sidebarY = interpolate(sidebarP, [0, 1], [18, 0]);

  // Per-element springs
  const chipP = spring({
    frame: frame - CHIP_DELAY,
    fps,
    config: { damping: 200 },
  });
  const titleP = spring({
    frame: frame - TITLE_DELAY,
    fps,
    config: { damping: 200 },
  });
  const descP = spring({
    frame: frame - DESC_DELAY,
    fps,
    config: { damping: 200 },
  });
  const toolsHeaderP = spring({
    frame: frame - TOOLS_DELAY,
    fps,
    config: { damping: 200 },
  });

  const sItem = (p: number) => ({
    opacity: interpolate(p, [0, 0.1], [0, 1], { extrapolateRight: "clamp" }),
    translateY: interpolate(p, [0, 1], [10, 0]),
  });

  // Publish button press
  const publishPressP = spring({
    frame: frame - PUBLISH_FRAME,
    fps,
    config: { damping: 8, stiffness: 400 },
  });
  const publishBtnScale = interpolate(
    publishPressP,
    [0, 0.2, 0.5, 1],
    [1, 0.91, 1.04, 1.0],
  );

  // Published state
  const isPublished = frame >= PUBLISHED_GATE;
  const publishedTransitionP = spring({
    frame: frame - PUBLISHED_GATE,
    fps,
    config: { damping: 200 },
  });
  const publishedOpacity = interpolate(
    publishedTransitionP,
    [0, 0.15],
    [0, 1],
    { extrapolateRight: "clamp" },
  );

  // Phase gates
  const isCreated = frame >= SIDEBAR_START;

  return (
    <AbsoluteFill
      style={{
        background: "#09090b",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <div
        style={{
          position: "absolute",
          inset: 0,
          background: "linear-gradient(135deg, #0f0f12 0%, #09090b 100%)",
        }}
      />
      <div
        style={{
          position: "absolute",
          inset: 0,
          background: "rgba(0,0,0,0.72)",
          backdropFilter: "blur(6px)",
          opacity: overlayOpacity,
        }}
      />

      {/* Published — top-of-screen text */}
      {isPublished && (
        <div
          style={{
            position: "absolute",
            top: 52,
            left: 0,
            right: 0,
            display: "flex",
            justifyContent: "center",
            alignItems: "center",
            gap: 10,
            opacity: publishedOpacity,
            transform: `translateY(${interpolate(publishedTransitionP, [0, 1], [-16, 0])}px)`,
            zIndex: 10,
          }}
        >
          <CheckmarkCircle02Icon
            width={28}
            height={28}
            style={{ color: "#22c55e" }}
          />
          <span
            style={{
              fontFamily: FONTS.body,
              fontSize: 26,
              fontWeight: 500,
              color: "#22c55e",
              letterSpacing: -0.2,
            }}
          >
            Published to marketplace
          </span>
        </div>
      )}

      {/* Modal shell */}
      <div
        style={{
          position: "relative",
          width: 1060,
          background: "#18181b",
          borderRadius: 30,
          overflow: "hidden",
          transform: `scale(${modalScale})`,
          opacity: modalOpacity,
          boxShadow:
            "0 32px 100px rgba(0,0,0,0.92), 0 0 0 1px rgba(255,255,255,0.07)",
        }}
      >
        {/* ── PHASE 1: CREATION FORM ────────────────────────────────────── */}
        {!isCreated && (
          <div style={{ opacity: formOpacity }}>
            <div
              style={{
                padding: "38px 42px 26px",
                display: "flex",
                flexDirection: "column",
                gap: 8,
                opacity: headerOpacity,
              }}
            >
              <h2
                style={{
                  fontFamily: FONTS.body,
                  fontSize: 40,
                  fontWeight: 600,
                  color: "#f4f4f5",
                  margin: 0,
                  lineHeight: 1.15,
                }}
              >
                New Integration
              </h2>
              <p
                style={{
                  fontFamily: FONTS.body,
                  fontSize: 20,
                  color: "#a1a1aa",
                  margin: 0,
                  lineHeight: 1.5,
                }}
              >
                Connect to external services using the Model Context Protocol
              </p>
            </div>

            <div style={{ height: 1, background: "rgba(255,255,255,0.06)" }} />

            <div
              style={{
                padding: "28px 42px 36px",
                display: "flex",
                flexDirection: "column",
                gap: 20,
              }}
            >
              <Field
                label="Name"
                value="Notion"
                placeholder="Integration name"
                delay={18}
                icon={<McpServerIcon size={22} style={{ color: "#71717a" }} />}
              />
              <TextareaField
                label="Description"
                value="Read and write pages, databases, and blocks in your Notion workspace"
                placeholder="What does this integration do?"
                delay={26}
              />
              <Field
                label="Server URL"
                value="https://mcp.notion.so/sse"
                placeholder="https://mcp.example.com/sse"
                delay={46}
                icon={<LinkIcon size={22} style={{ color: "#71717a" }} />}
              />
              <Field
                label="API Key"
                value="secret_notion_abc123def456"
                placeholder="sk-... or your API token"
                delay={64}
                icon={<KeyIcon size={22} style={{ color: "#71717a" }} />}
                type="password"
              />
              <div
                style={{
                  display: "flex",
                  justifyContent: "flex-end",
                  opacity: btnAppearOpacity,
                  marginTop: 4,
                }}
              >
                <div
                  style={{
                    fontFamily: FONTS.body,
                    fontSize: 18,
                    fontWeight: 600,
                    color: "#000",
                    background: "#00bbff",
                    borderRadius: 12,
                    padding: "14px 32px",
                    display: "flex",
                    alignItems: "center",
                    gap: 10,
                    transform: `scale(${createBtnScale})`,
                    boxShadow:
                      "0 4px 5px 0px rgba(0,187,255,0.25), 0 0 0 1px rgba(0,187,255,0.4), inset 0 1px 0 rgba(255,255,255,0.25)",
                  }}
                >
                  Create integration
                  <span
                    style={{
                      background: "rgba(0,0,0,0.12)",
                      borderRadius: 6,
                      padding: "2px 7px",
                      fontSize: 13,
                      color: "rgba(0,0,0,0.6)",
                    }}
                  >
                    ⌘↵
                  </span>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ── PHASE 2: SIDEBAR VIEW ─────────────────────────────────────── */}
        {isCreated && (
          <div
            style={{
              padding: "48px 56px 56px",
              display: "flex",
              flexDirection: "column",
              gap: 28,
              opacity: sidebarOpacity,
              transform: `translateY(${sidebarY}px)`,
            }}
          >
            {/* Integration icon */}
            <div
              style={{
                width: 90,
                height: 90,
                borderRadius: 18,
                background: "#27272a",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                overflow: "hidden",
              }}
            >
              <Img
                src={staticFile("images/icons/notion.webp")}
                style={{ width: 64, height: 64, objectFit: "contain" }}
              />
            </div>

            {/* Status chips */}
            <div
              style={{
                display: "flex",
                flexDirection: "row",
                gap: 10,
                alignItems: "center",
                opacity: sItem(chipP).opacity,
                transform: `translateY(${sItem(chipP).translateY}px)`,
              }}
            >
              <SidebarChip color="success">Connected</SidebarChip>
              <SidebarChip
                color="default"
                startContent={
                  <Img
                    src="https://github.com/aryanranderiya.png"
                    style={{
                      width: 22,
                      height: 22,
                      borderRadius: "50%",
                      objectFit: "cover",
                      flexShrink: 0,
                    }}
                  />
                }
              >
                Created by You
              </SidebarChip>
            </div>

            {/* Title */}
            <h1
              style={{
                fontFamily: FONTS.body,
                fontSize: 64,
                fontWeight: 600,
                color: "#f4f4f5",
                margin: 0,
                lineHeight: 1.1,
                opacity: sItem(titleP).opacity,
                transform: `translateY(${sItem(titleP).translateY}px)`,
              }}
            >
              Notion
            </h1>

            {/* Description */}
            <p
              style={{
                fontFamily: FONTS.body,
                fontSize: 26,
                fontWeight: 300,
                color: "#a1a1aa",
                margin: 0,
                lineHeight: 1.6,
                opacity: sItem(descP).opacity,
                transform: `translateY(${sItem(descP).translateY}px)`,
              }}
            >
              Read and write pages, databases, and blocks in your Notion
              workspace
            </p>

            {/* Button group — before publish: full text [Disconnect | Publish] */}
            {!isPublished && (
              <div
                style={{
                  display: "flex",
                  borderRadius: 14,
                  overflow: "hidden",
                  width: "100%",
                  transform: `scale(${frame >= PUBLISH_FRAME ? publishBtnScale : 1})`,
                  transformOrigin: "center",
                }}
              >
                <FlatBtn
                  icon={<Unlink04Icon width={26} height={26} />}
                  label="Disconnect"
                  color="danger"
                  delay={BTNS_DELAY}
                />
                <div
                  style={{
                    width: 1,
                    background: "rgba(255,255,255,0.08)",
                    flexShrink: 0,
                  }}
                />
                <FlatBtn
                  icon={<GlobalIcon width={26} height={26} />}
                  label="Publish"
                  color="primary"
                  delay={BTNS_DELAY + 6}
                  pressed={frame >= PUBLISH_FRAME}
                  framePressed={PUBLISH_FRAME}
                />
              </div>
            )}

            {/* Button group — after publish: icon-only [Disconnect | View | Unpublish | Share] */}
            {isPublished && (
              <div
                style={{
                  display: "flex",
                  borderRadius: 14,
                  overflow: "hidden",
                  width: "100%",
                  opacity: publishedOpacity,
                }}
              >
                <IconBtn
                  icon={<Unlink04Icon width={26} height={26} />}
                  color="danger"
                  opacity={1}
                />
                <div
                  style={{
                    width: 1,
                    background: "rgba(255,255,255,0.08)",
                    flexShrink: 0,
                  }}
                />
                <IconBtn
                  icon={<LinkSquareIcon width={26} height={26} />}
                  color="primary"
                  opacity={1}
                />
                <div
                  style={{
                    width: 1,
                    background: "rgba(255,255,255,0.08)",
                    flexShrink: 0,
                  }}
                />
                <IconBtn
                  icon={<RemoveCircleIcon width={26} height={26} />}
                  color="warning"
                  opacity={1}
                />
                <div
                  style={{
                    width: 1,
                    background: "rgba(255,255,255,0.08)",
                    flexShrink: 0,
                  }}
                />
                <IconBtn
                  icon={<Share08Icon width={26} height={26} />}
                  color="default"
                  opacity={1}
                />
              </div>
            )}

            {/* Available Tools header */}
            <div
              style={{
                fontFamily: FONTS.body,
                fontSize: 20,
                fontWeight: 500,
                color: "#71717a",
                textTransform: "uppercase",
                letterSpacing: 1.5,
                opacity: sItem(toolsHeaderP).opacity,
                transform: `translateY(${sItem(toolsHeaderP).translateY}px)`,
              }}
            >
              Available Tools ({TOOLS.length})
            </div>

            {/* Tool chips */}
            <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
              {TOOLS.map((tool, i) => (
                <ToolChip
                  key={tool}
                  label={tool}
                  delay={TOOLS_DELAY + 8 + i * 7}
                />
              ))}
            </div>
          </div>
        )}
      </div>
    </AbsoluteFill>
  );
};
