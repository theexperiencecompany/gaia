// biome-ignore-all lint/a11y/noSvgWithoutTitle: decorative chat-UI icons
// biome-ignore-all lint/suspicious/noArrayIndexKey: static demo content, never re-ordered
// biome-ignore-all lint/correctness/noUnusedFunctionParameters: API-compatible signature with gaia-ui
// biome-ignore-all lint/a11y/useAriaPropsSupportedByRole: decorative element
"use client";

import type React from "react";
import { cn } from "@/lib/utils";

export type ChatPlatform =
  | "imessage"
  | "whatsapp"
  | "slack"
  | "discord"
  | "telegram";

export interface ChatMessageItem {
  id?: string | number;
  from?: "me" | "them";
  text?: string;
  time?: string;
  author?: string;
  authorColor?: string;
  avatar?: string;
  status?: "sent" | "delivered" | "read";
  reactions?: { emoji: string; count: number }[];
  typing?: boolean;
}

export interface ChatDemoProps {
  platform: ChatPlatform;
  messages: ChatMessageItem[];
  title?: string;
  subtitle?: string;
  headerAvatar?: string;
  showComposer?: boolean;
  showHeader?: boolean;
  theme?: "light" | "dark";
  className?: string;
}

const DEFAULT_AVATAR = "/images/logos/macos.webp";

const SF_STACK =
  '-apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "Helvetica Neue", Helvetica, Arial, sans-serif';
const SLACK_STACK =
  '"Slack-Lato", "Lato", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif';
const DISCORD_STACK =
  '"gg sans", "Noto Sans", "Helvetica Neue", Helvetica, Arial, sans-serif';

export function ChatDemo({
  platform,
  messages,
  title,
  subtitle,
  headerAvatar,
  showComposer = true,
  showHeader = true,
  theme,
  className,
}: ChatDemoProps) {
  switch (platform) {
    case "imessage":
      return (
        <IMessageDemo
          messages={messages}
          title={title}
          subtitle={subtitle}
          headerAvatar={headerAvatar ?? DEFAULT_AVATAR}
          showComposer={showComposer}
          showHeader={showHeader}
          className={className}
        />
      );
    case "whatsapp":
      return (
        <WhatsAppDemo
          messages={messages}
          title={title}
          subtitle={subtitle}
          headerAvatar={headerAvatar ?? DEFAULT_AVATAR}
          showComposer={showComposer}
          showHeader={showHeader}
          className={className}
        />
      );
    case "slack":
      return (
        <SlackDemo
          messages={messages}
          title={title}
          subtitle={subtitle}
          showComposer={showComposer}
          showHeader={showHeader}
          theme={theme ?? "light"}
          className={className}
        />
      );
    case "discord":
      return (
        <DiscordDemo
          messages={messages}
          title={title}
          subtitle={subtitle}
          showComposer={showComposer}
          showHeader={showHeader}
          className={className}
        />
      );
    case "telegram":
      return (
        <TelegramDemo
          messages={messages}
          title={title}
          subtitle={subtitle}
          headerAvatar={headerAvatar ?? DEFAULT_AVATAR}
          showComposer={showComposer}
          showHeader={showHeader}
          className={className}
        />
      );
    default: {
      const _exhaustiveCheck: never = platform;
      throw new Error(`Unhandled ChatPlatform: ${_exhaustiveCheck}`);
    }
  }
}

/* =========================================================================
 * Shared curved bubble (the iMessage shape, reused by WhatsApp & Telegram)
 * ========================================================================= */

const TAIL_THEM =
  "M 20 0 L 20 2 A 16 16 0 0 1 4 18 L 0 18 L 0 17.54 A 10 10 0 0 0 7 8 L 7 0 Z";
const TAIL_ME =
  "M 0 0 L 0 2 A 16 16 0 0 0 16 18 L 20 18 L 20 17.54 A 10 10 0 0 1 13 8 L 13 0 Z";

interface CurvedBubbleProps {
  from: "me" | "them";
  tail: boolean;
  background: string;
  tailColor: string;
  color: string;
  children: React.ReactNode;
  /** Inline meta (time / ticks) shown at bottom-right of the bubble */
  meta?: React.ReactNode;
  maxWidthPct?: number;
  className?: string;
}

function CurvedBubble({
  from,
  tail,
  background,
  tailColor,
  color,
  children,
  meta,
  maxWidthPct = 78,
  className,
}: CurvedBubbleProps) {
  const isMe = from === "me";
  return (
    <div
      className={cn("relative", className)}
      style={{ maxWidth: `${maxWidthPct}%` }}
    >
      <div
        style={{
          background,
          color,
          padding: "7px 13px 8px",
          borderRadius: 18,
          fontSize: 15.5,
          lineHeight: "20px",
          letterSpacing: "-0.01em",
          wordBreak: "break-word",
          position: "relative",
          whiteSpace: "pre-wrap",
        }}
      >
        {children}
        {meta && (
          <span
            style={{
              display: "inline-block",
              verticalAlign: "bottom",
              marginLeft: 6,
              marginRight: -2,
              marginBottom: -1,
              fontSize: 11,
              lineHeight: "14px",
              letterSpacing: "-0.01em",
              whiteSpace: "nowrap",
              opacity: 0.95,
            }}
          >
            {meta}
          </span>
        )}
      </div>
      {tail && (
        <span
          aria-hidden="true"
          style={{
            position: "absolute",
            bottom: 0,
            [isMe ? "right" : "left"]: -7,
            width: 20,
            height: 18,
            background: tailColor,
            clipPath: `path('${isMe ? TAIL_ME : TAIL_THEM}')`,
          }}
        />
      )}
    </div>
  );
}

type CurvedThread = {
  from: "me" | "them";
  items: ChatMessageItem[];
};

function curvedThread(messages: ChatMessageItem[]): CurvedThread[] {
  const out: CurvedThread[] = [];
  for (const m of messages) {
    const from = m.from ?? "them";
    const last = out[out.length - 1];
    if (last && last.from === from) last.items.push(m);
    else out.push({ from, items: [m] });
  }
  return out;
}

/* =========================================================================
 * iMessage
 * ========================================================================= */

const IMESSAGE_GRADIENT = "linear-gradient(180deg, #309BFE 0%, #027BFF 100%)";
const IMESSAGE_THEM_BG = "#E9E9EB";
const IMESSAGE_TAIL_ME_COLOR = "#0E89FF";

function IMessageDemo({
  messages,
  title,
  subtitle,
  headerAvatar,
  showComposer,
  showHeader,
  className,
}: {
  messages: ChatMessageItem[];
  title?: string;
  subtitle?: string;
  headerAvatar?: string;
  showComposer: boolean;
  showHeader: boolean;
  className?: string;
}) {
  const grouped = curvedThread(messages);
  return (
    <div
      className={cn("flex h-full flex-col", className)}
      style={{ background: "#ffffff", fontFamily: SF_STACK, color: "#000" }}
    >
      {showHeader && (
        <div
          className="flex shrink-0 flex-col items-center justify-center"
          style={{ background: "#ffffff", padding: "2px 16px 10px" }}
        >
          <div
            className="overflow-hidden rounded-full"
            style={{ width: 54, height: 54, marginBottom: 5 }}
          >
            {/* biome-ignore lint/performance/noImgElement: tiny remote avatar */}
            <img
              src={headerAvatar}
              alt=""
              style={{ width: 54, height: 54, objectFit: "cover" }}
            />
          </div>
          <div
            className="flex items-center"
            style={{ fontSize: 14, color: "#000", fontWeight: 600, gap: 3 }}
          >
            <span style={{ letterSpacing: "-0.01em" }}>{title ?? "GAIA"}</span>
            <svg
              width="5"
              height="8"
              viewBox="0 0 7 11"
              fill="none"
              aria-hidden
            >
              <path
                d="M1 1l4.5 4.5L1 10"
                stroke="rgba(60,60,67,0.28)"
                strokeWidth="1.4"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </div>
          {subtitle && (
            <span
              style={{
                fontSize: 11,
                color: "rgba(60,60,67,0.55)",
                marginTop: 2,
              }}
            >
              {subtitle}
            </span>
          )}
        </div>
      )}
      <div
        className="flex flex-1 flex-col overflow-y-auto px-3 pb-3"
        style={{ scrollbarWidth: "none", gap: 8 }}
      >
        {grouped.map((group, gi) => {
          const groupTime = group.items[0].time;
          return (
            <div key={gi} className="flex flex-col" style={{ gap: 8 }}>
              {groupTime && (
                <div
                  className="self-center text-center"
                  style={{
                    fontSize: 11,
                    color: "rgba(60,60,67,0.6)",
                    fontWeight: 500,
                    letterSpacing: "-0.01em",
                    marginTop: gi === 0 ? 4 : 6,
                  }}
                >
                  {groupTime}
                </div>
              )}
              <div
                className={cn(
                  "flex flex-col",
                  group.from === "me" ? "items-end" : "items-start",
                )}
                style={{ gap: 2 }}
              >
                {group.items.map((m, i) => {
                  const isLast = i === group.items.length - 1;
                  const isMe = group.from === "me";
                  return (
                    <CurvedBubble
                      key={m.id ?? `${gi}-${i}`}
                      className="chat-bubble-pop"
                      from={group.from}
                      tail={isLast}
                      background={isMe ? IMESSAGE_GRADIENT : IMESSAGE_THEM_BG}
                      tailColor={
                        isMe ? IMESSAGE_TAIL_ME_COLOR : IMESSAGE_THEM_BG
                      }
                      color={isMe ? "#fff" : "#000"}
                    >
                      {m.typing ? (
                        <TypingDots
                          color={isMe ? "rgba(255,255,255,0.9)" : "#8e8e93"}
                        />
                      ) : (
                        m.text
                      )}
                    </CurvedBubble>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
      {showComposer && (
        <div
          className="flex shrink-0 items-end gap-2 px-2 pt-2 pb-1"
          style={{ background: "#ffffff" }}
        >
          <button
            type="button"
            aria-label="More"
            className="flex shrink-0 cursor-pointer items-center justify-center rounded-full transition-[filter,background] duration-150 hover:brightness-95 active:brightness-90"
            style={{
              width: 30,
              height: 30,
              background: "#E9E9EB",
              color: "rgba(60,60,67,0.7)",
            }}
          >
            <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden>
              <path
                d="M7 1v12M1 7h12"
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinecap="round"
              />
            </svg>
          </button>
          <div
            className="flex flex-1 items-center justify-between"
            style={{
              border: "1px solid rgba(60,60,67,0.18)",
              borderRadius: 18,
              padding: "5px 4px 5px 19px",
              background: "#fff",
              minHeight: 32,
            }}
          >
            <input
              type="text"
              placeholder="iMessage"
              className="chat-demo-input min-w-0 flex-1 border-0 bg-transparent p-0 outline-none placeholder:text-[rgba(60,60,67,0.5)]"
              style={{
                fontSize: 15,
                color: "#000",
                letterSpacing: "-0.01em",
                fontFamily: "inherit",
              }}
            />
            <button
              type="button"
              aria-label="Audio"
              className="ml-2 flex cursor-pointer items-center justify-center rounded-full transition-colors hover:bg-black/[0.06]"
              style={{ color: "rgba(60,60,67,0.7)", width: 22, height: 22 }}
            >
              <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden>
                <path
                  d="M8 1.5a2 2 0 0 0-2 2v4a2 2 0 0 0 4 0v-4a2 2 0 0 0-2-2Zm4 6a4 4 0 0 1-8 0H3a5 5 0 0 0 4.5 5V14h1v-1.5A5 5 0 0 0 13 7.5h-1Z"
                  fill="currentColor"
                />
              </svg>
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/* =========================================================================
 * WhatsApp — iMessage bubble shape + WhatsApp SVG colors and chrome.
 * Source: .context/attachments/WhatsApp Chat.svg
 * ========================================================================= */

function WhatsAppDemo({
  messages,
  title,
  subtitle,
  headerAvatar,
  showComposer,
  showHeader,
  className,
}: {
  messages: ChatMessageItem[];
  title?: string;
  subtitle?: string;
  headerAvatar?: string;
  showComposer: boolean;
  showHeader: boolean;
  className?: string;
}) {
  // Palette extracted from WhatsApp Chat.svg
  const bg = "#EFEFF4";
  const chromeBg = "#F6F6F6";
  const myBubble = "#DCF7C5";
  const theirBubble = "#FFFFFF";
  const textColor = "#060606";
  const metaColor = "rgba(0,0,0,0.45)";
  const accent = "#007AFF";

  const grouped = curvedThread(messages);

  return (
    <div
      className={cn("flex h-full flex-col", className)}
      style={{ background: bg, fontFamily: SF_STACK, color: textColor }}
    >
      {/* Header — iOS chrome from WhatsApp Chat.svg (#F6F6F6) */}
      {showHeader && (
        <div
          className="flex shrink-0 flex-col"
          style={{ background: chromeBg }}
        >
          <div
            className="grid items-center"
            style={{
              gridTemplateColumns: "1fr auto 1fr",
              padding: "6px 12px 8px",
              gap: 8,
            }}
          >
            <div className="flex items-center" style={{ color: accent }}>
              <svg
                width="12"
                height="20"
                viewBox="0 0 12 20"
                aria-hidden
                fill="none"
              >
                <path
                  d="M10 2 2 10l8 8"
                  stroke={accent}
                  strokeWidth="2.4"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </div>
            <div className="flex flex-col items-center" style={{ minWidth: 0 }}>
              <div
                className="overflow-hidden rounded-full"
                style={{ width: 32, height: 32 }}
              >
                {/* biome-ignore lint/performance/noImgElement: avatar */}
                <img
                  src={headerAvatar}
                  alt=""
                  style={{ width: 32, height: 32, objectFit: "cover" }}
                />
              </div>
              <span
                style={{
                  fontSize: 10,
                  marginTop: 2,
                  color: textColor,
                  letterSpacing: "-0.01em",
                  maxWidth: 140,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {title ?? "GAIA"}
              </span>
            </div>
            <div
              className="flex items-center justify-end"
              style={{ color: accent }}
            >
              <svg
                width="22"
                height="14"
                viewBox="0 0 22 14"
                aria-hidden
                fill="none"
              >
                <rect
                  x="0.5"
                  y="0.5"
                  width="15"
                  height="13"
                  rx="3"
                  stroke={accent}
                />
                <path
                  d="M16 4l5 -3v12l-5 -3z"
                  fill={accent}
                  stroke={accent}
                  strokeWidth="0.5"
                  strokeLinejoin="round"
                />
              </svg>
            </div>
          </div>
          <div style={{ height: 0.5, background: "rgba(60,60,67,0.18)" }} />
        </div>
      )}

      {/* Chat area — light gray with the WhatsApp doodle pattern */}
      <div
        className="flex flex-1 flex-col overflow-y-auto px-3 pb-3"
        style={{
          scrollbarWidth: "none",
          gap: 8,
          backgroundColor: bg,
          backgroundImage: 'url("/whatsapp-doodle.png")',
          backgroundRepeat: "repeat",
          backgroundSize: "404px auto",
          paddingTop: 8,
        }}
      >
        {grouped.map((group, gi) => {
          const isMe = group.from === "me";
          return (
            <div
              key={gi}
              className={cn(
                "flex flex-col",
                isMe ? "items-end" : "items-start",
              )}
              style={{ gap: 2 }}
            >
              {group.items.map((m, i) => {
                const isLast = i === group.items.length - 1;
                const showMeta = !m.typing && (m.time || (isMe && m.status));
                return (
                  <CurvedBubble
                    key={m.id ?? `${gi}-${i}`}
                    className="chat-bubble-pop"
                    from={group.from}
                    tail={isLast}
                    background={isMe ? myBubble : theirBubble}
                    tailColor={isMe ? myBubble : theirBubble}
                    color={textColor}
                    meta={
                      showMeta ? (
                        <span
                          style={{
                            color: metaColor,
                            display: "inline-flex",
                            alignItems: "center",
                            gap: 3,
                          }}
                        >
                          {m.time ?? ""}
                          {isMe && m.status && (
                            <WhatsAppTicks status={m.status} />
                          )}
                        </span>
                      ) : undefined
                    }
                  >
                    {m.typing ? <TypingDots color={metaColor} /> : m.text}
                  </CurvedBubble>
                );
              })}
            </div>
          );
        })}
      </div>

      {showComposer && (
        <div
          className="flex shrink-0 items-center gap-2 px-2 pt-2 pb-1.5"
          style={{ background: chromeBg }}
        >
          <button
            type="button"
            aria-label="Camera"
            className="flex cursor-pointer items-center justify-center rounded-full transition-colors hover:bg-black/[0.06]"
            style={{ width: 32, height: 32, color: "#3C3C43" }}
          >
            <CameraIcon />
          </button>
          <div
            className="flex flex-1 items-center justify-between gap-2"
            style={{
              background: "#FFFFFF",
              border: "0.5px solid #8E8E93",
              borderRadius: 16,
              padding: "0 6px 0 17px",
              height: 32,
              color: "#8E8E93",
            }}
          >
            <input
              type="text"
              placeholder="Message"
              className="chat-demo-input min-w-0 flex-1 border-0 bg-transparent p-0 outline-none placeholder:text-[#8E8E93]"
              style={{
                fontSize: 15,
                color: "#000",
                letterSpacing: "-0.01em",
                fontFamily: "inherit",
              }}
            />
            <button
              type="button"
              aria-label="Emoji"
              className="flex shrink-0 cursor-pointer items-center justify-center rounded-full transition-colors hover:bg-black/[0.06]"
              style={{ color: "#8E8E93", width: 22, height: 22 }}
            >
              <EmojiIcon size={18} />
            </button>
          </div>
          <button
            type="button"
            aria-label="Voice message"
            className="flex cursor-pointer items-center justify-center rounded-full transition-colors hover:bg-black/[0.06]"
            style={{ width: 32, height: 32, color: "#3C3C43" }}
          >
            <MicIcon />
          </button>
        </div>
      )}
    </div>
  );
}

function WhatsAppTicks({ status }: { status: "sent" | "delivered" | "read" }) {
  const color = status === "read" ? "#3497F9" : "rgba(0,0,0,0.4)";
  if (status === "sent") {
    return (
      <svg width="14" height="11" viewBox="0 0 14 11" aria-hidden fill="none">
        <path
          d="M1 6l3.5 3.5L11 2"
          stroke={color}
          strokeWidth="1.6"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    );
  }
  // TickDouble02-style: two clean overlapping check marks
  return (
    <svg width="16" height="11" viewBox="0 0 18 14" aria-hidden fill="none">
      <path
        d="M1 7l3.2 3.5L11 3.5"
        stroke={color}
        strokeWidth="1.7"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M6 7l3.2 3.5L17 3.5"
        stroke={color}
        strokeWidth="1.7"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/* =========================================================================
 * Telegram — iMessage bubble shape + Telegram SVG palette and chrome.
 * Source: .context/attachments/Telegram Chat.svg
 * ========================================================================= */

function TelegramDemo({
  messages,
  title,
  subtitle,
  headerAvatar,
  showComposer,
  showHeader,
  className,
}: {
  messages: ChatMessageItem[];
  title?: string;
  subtitle?: string;
  headerAvatar?: string;
  showComposer: boolean;
  showHeader: boolean;
  className?: string;
}) {
  // Palette extracted from Telegram Chat.svg
  const chromeBg = "#F6F6F6";
  const blueOverlay = "#2B78CD"; // 50% over the doodle pattern
  const myBubble = "#E1FEC6";
  const theirBubble = "#FFFFFF";
  const textColor = "#060606";
  const metaColor = "#858E99";
  const myMeta = "#3EAA3C";
  const accent = "#037EE5";

  const grouped = curvedThread(messages);

  return (
    <div
      className={cn("flex h-full flex-col", className)}
      style={{ fontFamily: SF_STACK, color: textColor, background: chromeBg }}
    >
      {/* iOS header */}
      {showHeader && (
        <div
          className="flex shrink-0 flex-col"
          style={{ background: chromeBg }}
        >
          <div
            className="grid items-center"
            style={{
              gridTemplateColumns: "1fr auto 1fr",
              padding: "6px 12px 8px",
              gap: 8,
            }}
          >
            <div className="flex items-center" style={{ color: accent }}>
              <svg
                width="12"
                height="20"
                viewBox="0 0 12 20"
                aria-hidden
                fill="none"
              >
                <path
                  d="M10 2 2 10l8 8"
                  stroke={accent}
                  strokeWidth="2.4"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
              <span
                style={{
                  fontSize: 17,
                  marginLeft: 8,
                  letterSpacing: "-0.01em",
                }}
              >
                Back
              </span>
            </div>
            <div className="flex flex-col items-center" style={{ minWidth: 0 }}>
              <span
                style={{
                  fontSize: 17,
                  fontWeight: 600,
                  letterSpacing: "-0.01em",
                  color: textColor,
                  maxWidth: 160,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {title ?? "GAIA"}
              </span>
              <span style={{ fontSize: 12, color: metaColor, marginTop: 1 }}>
                {subtitle ?? "last seen recently"}
              </span>
            </div>
            <div
              className="flex items-center justify-end"
              style={{ color: accent }}
            >
              <div
                className="overflow-hidden rounded-full"
                style={{ width: 32, height: 32 }}
              >
                {/* biome-ignore lint/performance/noImgElement: avatar */}
                <img
                  src={headerAvatar}
                  alt=""
                  style={{ width: 32, height: 32, objectFit: "cover" }}
                />
              </div>
            </div>
          </div>
          <div style={{ height: 0.5, background: "rgba(60,60,67,0.18)" }} />
        </div>
      )}

      {/* Chat area: blue overlay + Telegram doodle pattern */}
      <div
        className="flex flex-1 flex-col overflow-y-auto px-3 pb-3"
        style={{
          scrollbarWidth: "none",
          gap: 8,
          backgroundColor: blueOverlay,
          backgroundImage:
            'linear-gradient(rgba(43,120,205,0.5), rgba(43,120,205,0.5)), url("/telegram-doodle.png")',
          backgroundSize: "auto, 480px auto",
          backgroundRepeat: "repeat",
          paddingTop: 8,
        }}
      >
        {grouped.map((group, gi) => {
          const isMe = group.from === "me";
          return (
            <div
              key={gi}
              className={cn(
                "flex flex-col",
                isMe ? "items-end" : "items-start",
              )}
              style={{ gap: 2 }}
            >
              {group.items.map((m, i) => {
                const isLast = i === group.items.length - 1;
                const showMeta = !m.typing && (m.time || (isMe && m.status));
                return (
                  <CurvedBubble
                    key={m.id ?? `${gi}-${i}`}
                    className="chat-bubble-pop"
                    from={group.from}
                    tail={isLast}
                    background={isMe ? myBubble : theirBubble}
                    tailColor={isMe ? myBubble : theirBubble}
                    color={textColor}
                    meta={
                      showMeta ? (
                        <span
                          style={{
                            color: isMe ? myMeta : metaColor,
                            display: "inline-flex",
                            alignItems: "center",
                            gap: 3,
                          }}
                        >
                          {m.time ?? ""}
                          {isMe && m.status && (
                            <TelegramTicks status={m.status} color={myMeta} />
                          )}
                        </span>
                      ) : undefined
                    }
                  >
                    {m.typing ? (
                      <TypingDots color={isMe ? myMeta : metaColor} />
                    ) : (
                      m.text
                    )}
                  </CurvedBubble>
                );
              })}
            </div>
          );
        })}
      </div>

      {showComposer && (
        <div
          className="flex shrink-0 items-center gap-2 px-2 pt-2 pb-1.5"
          style={{ background: chromeBg }}
        >
          <button
            type="button"
            aria-label="Attach"
            className="flex cursor-pointer items-center justify-center rounded-full transition-colors hover:bg-black/[0.06]"
            style={{ width: 30, height: 30, color: accent }}
          >
            <AttachmentIcon />
          </button>
          <div
            className="flex flex-1 items-center justify-between gap-2"
            style={{
              background: "#FFFFFF",
              border: "0.5px solid #D1D1D6",
              borderRadius: 16,
              padding: "0 8px 0 19px",
              height: 32,
              color: metaColor,
            }}
          >
            <input
              type="text"
              placeholder="Message"
              className="chat-demo-input min-w-0 flex-1 border-0 bg-transparent p-0 outline-none placeholder:text-[#858E99]"
              style={{
                fontSize: 15,
                color: "#000",
                letterSpacing: "-0.01em",
                fontFamily: "inherit",
              }}
            />
            <button
              type="button"
              aria-label="Emoji"
              className="flex shrink-0 cursor-pointer items-center justify-center rounded-full transition-colors hover:bg-black/[0.06]"
              style={{ color: metaColor, width: 22, height: 22 }}
            >
              <EmojiIcon size={18} />
            </button>
          </div>
          <button
            type="button"
            aria-label="Voice"
            className="flex cursor-pointer items-center justify-center rounded-full transition-colors hover:bg-black/[0.06]"
            style={{ width: 30, height: 30, color: accent }}
          >
            <MicIcon />
          </button>
        </div>
      )}
    </div>
  );
}

function TelegramTicks({
  status,
  color,
}: {
  status: "sent" | "delivered" | "read";
  color: string;
}) {
  if (status === "sent") {
    return (
      <svg width="14" height="11" viewBox="0 0 14 11" aria-hidden fill="none">
        <path
          d="M1 6l3.5 3.5L11 2"
          stroke={color}
          strokeWidth="1.4"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    );
  }
  return (
    <svg width="16" height="11" viewBox="0 0 16 11" aria-hidden fill="none">
      <path
        d="M0.5 6.5l3.5 3.5L10.5 2.5"
        stroke={color}
        strokeWidth="1.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M4 6.5l3.5 3.5L13.5 2.5"
        stroke={color}
        strokeWidth="1.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/* =========================================================================
 * Slack
 * ========================================================================= */

function SlackDemo({
  messages,
  title,
  subtitle,
  showComposer,
  showHeader,
  theme,
  className,
}: {
  messages: ChatMessageItem[];
  title?: string;
  subtitle?: string;
  showComposer: boolean;
  showHeader: boolean;
  theme: "light" | "dark";
  className?: string;
}) {
  const isDark = theme === "dark";
  const bg = isDark ? "#1A1D21" : "#FFFFFF";
  const fg = isDark ? "#D1D2D3" : "#1D1C1D";
  const muted = isDark ? "#ABABAD" : "#616061";
  const headerBorder = isDark ? "#2F3236" : "#E8E8E8";

  const groups = groupByAuthor(messages);

  return (
    <div
      className={cn("flex h-full flex-col", className)}
      style={{ background: bg, color: fg, fontFamily: SLACK_STACK }}
    >
      {showHeader && (
        <div
          className="flex shrink-0 items-center justify-between border-b px-4"
          style={{ borderColor: headerBorder, height: 56 }}
        >
          <div className="flex flex-col leading-tight">
            <div
              className="flex items-center gap-1"
              style={{ fontWeight: 700, fontSize: 16 }}
            >
              <span style={{ color: muted, fontWeight: 400, marginRight: 2 }}>
                #
              </span>
              {title ?? "general"}
              <svg
                width="12"
                height="12"
                viewBox="0 0 20 20"
                aria-hidden
                style={{ marginLeft: 4 }}
              >
                <path
                  d="M5 8l5 5 5-5"
                  fill="none"
                  stroke={fg}
                  strokeWidth="1.8"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </div>
            <span style={{ fontSize: 12, color: muted }}>
              {subtitle ?? "Add a topic"}
            </span>
          </div>
          <div className="flex items-center gap-2" style={{ color: muted }}>
            <button
              type="button"
              aria-label="Activity"
              className="flex cursor-pointer items-center justify-center rounded-full transition-colors hover:bg-black/[0.06]"
              style={{ width: 32, height: 32 }}
            >
              <svg
                width="22"
                height="22"
                viewBox="0 0 24 24"
                aria-hidden
                fill="currentColor"
              >
                <path d="M12 21a9 9 0 1 1 0-18 9 9 0 0 1 0 18Zm0-2a7 7 0 1 0 0-14 7 7 0 0 0 0 14Zm-1-10h2v4h3v2h-5V9Z" />
              </svg>
            </button>
            <button
              type="button"
              aria-label="Search"
              className="flex cursor-pointer items-center justify-center rounded-full transition-colors hover:bg-black/[0.06]"
              style={{ width: 32, height: 32 }}
            >
              <svg
                width="22"
                height="22"
                viewBox="0 0 24 24"
                aria-hidden
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
              >
                <circle cx="11" cy="11" r="7" />
                <path d="m20 20-4-4" strokeLinecap="round" />
              </svg>
            </button>
          </div>
        </div>
      )}
      <div
        className="flex flex-1 flex-col overflow-y-auto py-3"
        style={{ scrollbarWidth: "none", gap: 12 }}
      >
        {groups.map((g, gi) => (
          <div
            key={gi}
            className="chat-bubble-pop flex items-start gap-2"
            style={{ padding: "0 16px" }}
          >
            <div
              className="shrink-0 overflow-hidden"
              style={{
                width: 36,
                height: 36,
                borderRadius: 6,
                marginTop: 4,
              }}
            >
              {/* biome-ignore lint/performance/noImgElement: avatar */}
              <img
                src={g.author?.avatar ?? DEFAULT_AVATAR}
                alt=""
                style={{ width: 36, height: 36, objectFit: "cover" }}
              />
            </div>
            <div className="flex min-w-0 flex-1 flex-col">
              <div className="flex items-baseline gap-2">
                <span
                  style={{
                    fontWeight: 900,
                    fontSize: 15,
                    color: fg,
                    letterSpacing: "-0.01em",
                  }}
                >
                  {g.author?.name ?? "Unknown"}
                </span>
                <span style={{ fontSize: 12, color: muted }}>
                  {g.items[0].time ?? ""}
                </span>
              </div>
              <div className="flex flex-col" style={{ gap: 2 }}>
                {g.items.map((m, i) => (
                  <div
                    key={m.id ?? `${gi}-${i}`}
                    style={{
                      fontSize: 15,
                      lineHeight: "22px",
                      color: fg,
                      wordBreak: "break-word",
                      whiteSpace: "pre-wrap",
                    }}
                  >
                    {m.typing ? (
                      <TypingDots color={muted} />
                    ) : (
                      renderSlackText(m.text ?? "", isDark)
                    )}
                  </div>
                ))}
              </div>
              {g.items.some((m) => m.reactions?.length) && (
                <div className="mt-1 flex flex-wrap gap-1">
                  {g.items.flatMap((m) =>
                    (m.reactions ?? []).map((r, ri) => (
                      <span
                        key={`${ri}-${r.emoji}`}
                        className="inline-flex items-center gap-1"
                        style={{
                          padding: "1px 7px",
                          borderRadius: 12,
                          border: `1px solid ${isDark ? "#3a3d42" : "#DDDDDD"}`,
                          background: isDark ? "#26282C" : "#F1F4F7",
                          fontSize: 12,
                          fontWeight: 700,
                          color: isDark ? "#9DB0CA" : "#1264A3",
                        }}
                      >
                        <span style={{ fontSize: 13 }}>{r.emoji}</span>
                        {r.count}
                      </span>
                    )),
                  )}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
      {showComposer && (
        <div className="shrink-0 px-3 pt-2 pb-1.5">
          <div
            className="flex flex-col overflow-hidden"
            style={{
              border: `1px solid ${isDark ? "#565856" : "#BABBBC"}`,
              borderRadius: 8,
              background: isDark ? "#222529" : "#fff",
            }}
          >
            {/* Formatting toolbar */}
            <div
              className="flex items-center"
              style={{
                height: 32,
                padding: "0 6px",
                color: muted,
                gap: 2,
                borderBottom: `1px solid ${isDark ? "#3a3d42" : "#E8E8E8"}`,
              }}
            >
              <SlackToolbarButton label="Bold">
                <path
                  fill="currentColor"
                  fillRule="evenodd"
                  d="M4 2.75A.75.75 0 0 1 4.75 2h6.343a3.91 3.91 0 0 1 3.88 3.449A2 2 0 0 1 15 5.84l.001.067a3.9 3.9 0 0 1-1.551 3.118A4.627 4.627 0 0 1 11.875 18H4.75a.75.75 0 0 1-.75-.75V9.5a.8.8 0 0 1 .032-.218A.8.8 0 0 1 4 9.065zm2.5 5.565h3.593a2.157 2.157 0 1 0 0-4.315H6.5zm4.25 1.935H6.5v5.5h4.25a2.75 2.75 0 1 0 0-5.5"
                  clipRule="evenodd"
                />
              </SlackToolbarButton>
              <SlackToolbarButton label="Italic">
                <path
                  fill="currentColor"
                  fillRule="evenodd"
                  d="M7 2.75A.75.75 0 0 1 7.75 2h7.5a.75.75 0 0 1 0 1.5H12.3l-2.6 13h2.55a.75.75 0 0 1 0 1.5h-7.5a.75.75 0 0 1 0-1.5H7.7l2.6-13H7.75A.75.75 0 0 1 7 2.75"
                  clipRule="evenodd"
                />
              </SlackToolbarButton>
              <SlackToolbarButton label="Underline">
                <path
                  fill="currentColor"
                  d="M17.25 17.12a.75.75 0 0 1 0 1.5H2.75a.75.75 0 0 1 0-1.5zM14.5 1.63a.75.75 0 0 1 .75.75v8a5.25 5.25 0 1 1-10.5 0v-8a.75.75 0 0 1 1.5 0v8a3.75 3.75 0 0 0 7.5 0v-8a.75.75 0 0 1 .75-.75"
                />
              </SlackToolbarButton>
              <SlackToolbarButton label="Strike">
                <path
                  fill="currentColor"
                  fillRule="evenodd"
                  d="M11.721 3.84c-.91-.334-2.028-.36-3.035-.114-1.51.407-2.379 1.861-2.164 3.15C6.718 8.051 7.939 9.5 11.5 9.5l.027.001h5.723a.75.75 0 0 1 0 1.5H2.75a.75.75 0 0 1 0-1.5h3.66c-.76-.649-1.216-1.468-1.368-2.377-.347-2.084 1.033-4.253 3.265-4.848l.007-.002.007-.002c1.252-.307 2.68-.292 3.915.16 1.252.457 2.337 1.381 2.738 2.874a.75.75 0 0 1-1.448.39c-.25-.925-.91-1.528-1.805-1.856m2.968 9.114a.75.75 0 1 0-1.378.59c.273.64.186 1.205-.13 1.674-.333.492-.958.925-1.82 1.137-.989.243-1.991.165-3.029-.124-.93-.26-1.613-.935-1.858-1.845a.75.75 0 0 0-1.448.39c.388 1.441 1.483 2.503 2.903 2.9 1.213.338 2.486.456 3.79.135 1.14-.28 2.12-.889 2.704-1.753.6-.888.743-1.992.266-3.104"
                  clipRule="evenodd"
                />
              </SlackToolbarButton>
              <SlackToolbarSeparator dark={isDark} />
              <SlackToolbarButton label="Link">
                <path
                  fill="currentColor"
                  fillRule="evenodd"
                  d="M12.306 3.756a2.75 2.75 0 0 1 3.889 0l.05.05a2.75 2.75 0 0 1 0 3.889l-3.18 3.18a2.75 2.75 0 0 1-3.98-.095l-.03-.034a.75.75 0 0 0-1.11 1.009l.03.034a4.25 4.25 0 0 0 6.15.146l3.18-3.18a4.25 4.25 0 0 0 0-6.01l-.05-.05a4.25 4.25 0 0 0-6.01 0L9.47 4.47a.75.75 0 1 0 1.06 1.06zm-4.611 12.49a2.75 2.75 0 0 1-3.89 0l-.05-.051a2.75 2.75 0 0 1 0-3.89l3.18-3.179a2.75 2.75 0 0 1 3.98.095l.03.034a.75.75 0 1 0 1.11-1.01l-.03-.033a4.25 4.25 0 0 0-6.15-.146l-3.18 3.18a4.25 4.25 0 0 0 0 6.01l.05.05a4.25 4.25 0 0 0 6.01 0l1.775-1.775a.75.75 0 0 0-1.06-1.06z"
                  clipRule="evenodd"
                />
              </SlackToolbarButton>
              <SlackToolbarButton label="Ordered list">
                <path
                  fill="currentColor"
                  fillRule="evenodd"
                  d="M3.792 2.094A.5.5 0 0 1 4 2.5V6h1a.5.5 0 1 1 0 1H2a.5.5 0 1 1 0-1h1V3.194l-.842.28a.5.5 0 0 1-.316-.948l1.5-.5a.5.5 0 0 1 .45.068M7.75 3.5a.75.75 0 0 0 0 1.5h10a.75.75 0 0 0 0-1.5zM7 10.75a.75.75 0 0 1 .75-.75h10a.75.75 0 0 1 0 1.5h-10a.75.75 0 0 1-.75-.75m0 6.5a.75.75 0 0 1 .75-.75h10a.75.75 0 0 1 0 1.5h-10a.75.75 0 0 1-.75-.75m-4.293-3.36a1 1 0 0 1 .793-.39c.49 0 .75.38.75.75 0 .064-.033.194-.173.409a5 5 0 0 1-.594.711c-.256.267-.552.548-.87.848l-.088.084a42 42 0 0 0-.879.845A.5.5 0 0 0 2 18h3a.5.5 0 0 0 0-1H3.242l.058-.055c.316-.298.629-.595.904-.882a6 6 0 0 0 .711-.859c.18-.277.335-.604.335-.954 0-.787-.582-1.75-1.75-1.75a2 2 0 0 0-1.81 1.147.5.5 0 1 0 .905.427 1 1 0 0 1 .112-.184"
                  clipRule="evenodd"
                />
              </SlackToolbarButton>
              <SlackToolbarButton label="Bullet list">
                <path
                  fill="currentColor"
                  fillRule="evenodd"
                  d="M4 3a1 1 0 1 1-2 0 1 1 0 0 1 2 0m3 0a.75.75 0 0 1 .75-.75h10a.75.75 0 0 1 0 1.5h-10A.75.75 0 0 1 7 3m.75 6.25a.75.75 0 0 0 0 1.5h10a.75.75 0 0 0 0-1.5zm0 7a.75.75 0 0 0 0 1.5h10a.75.75 0 0 0 0-1.5zM3 11a1 1 0 1 0 0-2 1 1 0 0 0 0 2m0 7a1 1 0 1 0 0-2 1 1 0 0 0 0 2"
                  clipRule="evenodd"
                />
              </SlackToolbarButton>
              <SlackToolbarSeparator dark={isDark} />
              <SlackToolbarButton label="Quote">
                <path
                  fill="currentColor"
                  fillRule="evenodd"
                  d="M3.5 2.75a.75.75 0 0 0-1.5 0v14.5a.75.75 0 0 0 1.5 0zM6.75 3a.75.75 0 0 0 0 1.5h8.5a.75.75 0 0 0 0-1.5zM6 10.25a.75.75 0 0 1 .75-.75h10.5a.75.75 0 0 1 0 1.5H6.75a.75.75 0 0 1-.75-.75m.75 5.25a.75.75 0 0 0 0 1.5h7.5a.75.75 0 0 0 0-1.5z"
                  clipRule="evenodd"
                />
              </SlackToolbarButton>
              <SlackToolbarButton label="Code">
                <path
                  fill="currentColor"
                  fillRule="evenodd"
                  d="M12.058 3.212c.396.12.62.54.5.936L8.87 16.29a.75.75 0 1 1-1.435-.436l3.686-12.143a.75.75 0 0 1 .936-.5M5.472 6.24a.75.75 0 0 1 .005 1.06l-2.67 2.693 2.67 2.691a.75.75 0 1 1-1.065 1.057l-3.194-3.22a.75.75 0 0 1 0-1.056l3.194-3.22a.75.75 0 0 1 1.06-.005m9.044 1.06a.75.75 0 1 1 1.065-1.056l3.194 3.221a.75.75 0 0 1 0 1.057l-3.194 3.219a.75.75 0 0 1-1.065-1.057l2.67-2.69z"
                  clipRule="evenodd"
                />
              </SlackToolbarButton>
              <SlackToolbarButton label="Code block">
                <path
                  fill="currentColor"
                  fillRule="evenodd"
                  d="M9.212 2.737a.75.75 0 1 0-1.424-.474l-2.5 7.5a.75.75 0 0 0 1.424.474zm6.038.265a.75.75 0 0 0 0 1.5h2a.25.25 0 0 1 .25.25v11.5a.25.25 0 0 1-.25.25h-13a.25.25 0 0 1-.25-.25v-3.5a.75.75 0 0 0-1.5 0v3.5c0 .966.784 1.75 1.75 1.75h13a1.75 1.75 0 0 0 1.75-1.75v-11.5a1.75 1.75 0 0 0-1.75-1.75zm-3.69.5a.75.75 0 1 0-1.12.996l1.556 1.754-1.556 1.75a.75.75 0 1 0 1.12.997l2-2.249a.75.75 0 0 0 0-.996zM3.999 9.061a.75.75 0 0 1-1.058-.062l-2-2.249a.75.75 0 0 1 0-.996l2-2.252a.75.75 0 1 1 1.12.996L2.504 6.252l1.557 1.75a.75.75 0 0 1-.062 1.059"
                  clipRule="evenodd"
                />
              </SlackToolbarButton>
            </div>

            {/* Text input area */}
            <textarea
              rows={1}
              placeholder={`Message #${title ?? "general"}`}
              className={cn(
                "chat-demo-input resize-none border-0 bg-transparent outline-none",
                isDark
                  ? "placeholder:text-[#ABABAD]"
                  : "placeholder:text-[#616061]",
              )}
              style={{
                padding: "10px 12px",
                fontSize: 15,
                color: fg,
                minHeight: 44,
                lineHeight: "20px",
                fontFamily: "inherit",
              }}
            />

            {/* Footer toolbar */}
            <div
              className="flex items-center justify-between"
              style={{ padding: "0 6px 6px", color: muted }}
            >
              <div className="flex items-center gap-1">
                <SlackToolbarButton label="Attach">
                  <path
                    fill="currentColor"
                    fillRule="evenodd"
                    d="M10.75 3.25a.75.75 0 0 0-1.5 0v6H3.251L3.25 10v-.75a.75.75 0 0 0 0 1.5V10v.75h6v6a.75.75 0 0 0 1.5 0v-6h6a.75.75 0 0 0 0-1.5h-6z"
                    clipRule="evenodd"
                  />
                </SlackToolbarButton>
                <SlackToolbarButton label="Formatting">
                  <path
                    fill="currentColor"
                    fillRule="evenodd"
                    d="M6.941 3.952c-.459-1.378-2.414-1.363-2.853.022l-4.053 12.8a.75.75 0 0 0 1.43.452l1.101-3.476h6.06l1.163 3.487a.75.75 0 1 0 1.423-.474zm1.185 8.298L5.518 4.427 3.041 12.25zm6.198-5.537a4.74 4.74 0 0 1 3.037-.081A3.74 3.74 0 0 1 20 10.208V17a.75.75 0 0 1-1.5 0v-.745a8 8 0 0 1-2.847 1.355 3 3 0 0 1-3.15-1.143C10.848 14.192 12.473 11 15.287 11H18.5v-.792c0-.984-.641-1.853-1.581-2.143a3.24 3.24 0 0 0-2.077.056l-.242.089a2.22 2.22 0 0 0-1.34 1.382l-.048.145a.75.75 0 0 1-1.423-.474l.048-.145a3.72 3.72 0 0 1 2.244-2.315zM18.5 12.5h-3.213c-1.587 0-2.504 1.801-1.57 3.085.357.491.98.717 1.572.57a6.5 6.5 0 0 0 2.47-1.223l.741-.593z"
                    clipRule="evenodd"
                  />
                </SlackToolbarButton>
                <SlackToolbarButton label="Emoji">
                  <path
                    fill="currentColor"
                    fillRule="evenodd"
                    d="M2.5 10a7.5 7.5 0 1 1 15 0 7.5 7.5 0 0 1-15 0M10 1a9 9 0 1 0 0 18 9 9 0 0 0 0-18M7.5 9.5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3M14 8a1.5 1.5 0 1 1-3 0 1.5 1.5 0 0 1 3 0m-6.385 3.766a.75.75 0 1 0-1.425.468C6.796 14.08 8.428 15 10.027 15s3.23-.92 3.838-2.766a.75.75 0 1 0-1.425-.468c-.38 1.155-1.38 1.734-2.413 1.734s-2.032-.58-2.412-1.734"
                    clipRule="evenodd"
                  />
                </SlackToolbarButton>
                <SlackToolbarButton label="Mention">
                  <path
                    fill="currentColor"
                    fillRule="evenodd"
                    d="M2.5 10a7.5 7.5 0 1 1 15 0v.645c0 1.024-.83 1.855-1.855 1.855a1.145 1.145 0 0 1-1.145-1.145V6.75a.75.75 0 0 0-1.494-.098 4.5 4.5 0 1 0 .465 6.212A2.64 2.64 0 0 0 15.646 14 3.355 3.355 0 0 0 19 10.645V10a9 9 0 1 0-3.815 7.357.75.75 0 1 0-.865-1.225A7.5 7.5 0 0 1 2.5 10m7.5 3a3 3 0 1 0 0-6 3 3 0 0 0 0 6"
                    clipRule="evenodd"
                  />
                </SlackToolbarButton>
                <SlackToolbarButton label="More options">
                  <path
                    fill="currentColor"
                    d="M14.5 10a1.75 1.75 0 1 1 3.5 0 1.75 1.75 0 0 1-3.5 0m-6.25 0a1.75 1.75 0 1 1 3.5 0 1.75 1.75 0 0 1-3.5 0M2 10a1.75 1.75 0 1 1 3.5 0A1.75 1.75 0 0 1 2 10"
                  />
                </SlackToolbarButton>
              </div>
              <div
                className="flex items-stretch overflow-hidden"
                style={{
                  borderRadius: 6,
                  border: `1px solid ${isDark ? "#3a3d42" : "#E1E1E1"}`,
                  color: muted,
                }}
              >
                <button
                  type="button"
                  aria-label="Send"
                  className="flex cursor-pointer items-center justify-center transition-colors hover:bg-black/[0.06] dark:hover:bg-white/[0.08]"
                  style={{ width: 24, height: 22, color: muted }}
                >
                  <svg width="14" height="14" viewBox="0 0 20 20" aria-hidden>
                    <path
                      fill="currentColor"
                      d="M1.5 2.106c0-.462.498-.754.901-.528l15.7 7.714a.73.73 0 0 1 .006 1.307L2.501 18.46l-.07.017a.754.754 0 0 1-.931-.733v-4.572c0-1.22.971-2.246 2.213-2.268l6.547-.17c.27-.01.75-.243.75-.797 0-.553-.5-.795-.75-.795l-6.547-.171C2.47 8.95 1.5 7.924 1.5 6.704z"
                    />
                  </svg>
                </button>
                <div
                  style={{
                    width: 1,
                    background: isDark ? "#3a3d42" : "#E1E1E1",
                  }}
                />
                <button
                  type="button"
                  aria-label="Schedule"
                  className="flex cursor-pointer items-center justify-center transition-colors hover:bg-black/[0.06] dark:hover:bg-white/[0.08]"
                  style={{ width: 20, height: 22, color: muted }}
                >
                  <svg width="12" height="12" viewBox="0 0 20 20" aria-hidden>
                    <path
                      fill="currentColor"
                      fillRule="evenodd"
                      d="M5.72 7.47a.75.75 0 0 1 1.06 0L10 10.69l3.22-3.22a.75.75 0 1 1 1.06 1.06l-3.75 3.75a.75.75 0 0 1-1.06 0L5.72 8.53a.75.75 0 0 1 0-1.06"
                      clipRule="evenodd"
                    />
                  </svg>
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function SlackToolbarButton({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      className="flex cursor-pointer items-center justify-center rounded transition-colors hover:bg-black/[0.06] dark:hover:bg-white/[0.08]"
      style={{ width: 26, height: 24 }}
    >
      <svg width="18" height="18" viewBox="0 0 20 20" aria-hidden>
        {children}
      </svg>
    </button>
  );
}

function SlackToolbarSeparator({ dark }: { dark: boolean }) {
  return (
    <span
      aria-hidden
      style={{
        display: "inline-block",
        width: 1,
        height: 16,
        margin: "0 4px",
        background: dark ? "#3a3d42" : "#E1E1E1",
      }}
    />
  );
}

function renderSlackText(text: string, dark: boolean) {
  const parts = text.split(/(@\w+|#\w+|`[^`]+`)/g);
  return parts.map((p, i) => {
    if (/^@\w+/.test(p)) {
      return (
        <span
          key={i}
          style={{
            background: dark ? "rgba(29,155,209,0.18)" : "#E8F5FA",
            color: dark ? "#1D9BD1" : "#1264A3",
            padding: "1px 3px",
            borderRadius: 3,
            fontWeight: 600,
          }}
        >
          {p}
        </span>
      );
    }
    if (/^#\w+/.test(p)) {
      return (
        <span
          key={i}
          style={{ color: dark ? "#1D9BD1" : "#1264A3", fontWeight: 600 }}
        >
          {p}
        </span>
      );
    }
    if (/^`[^`]+`$/.test(p)) {
      return (
        <code
          key={i}
          style={{
            background: dark ? "#222529" : "#F8F8F8",
            border: `1px solid ${dark ? "#3a3d42" : "#E8E8E8"}`,
            borderRadius: 3,
            padding: "0 4px",
            fontFamily: 'Menlo, Consolas, "Liberation Mono", monospace',
            fontSize: 12,
            color: "#E01E5A",
          }}
        >
          {p.slice(1, -1)}
        </code>
      );
    }
    return <span key={i}>{p}</span>;
  });
}

/* =========================================================================
 * Discord — chrome and composer matched to the iOS screenshot
 * (CleanShot 2026-05-11 at 13.05.53@2x.png)
 * ========================================================================= */

function DiscordDemo({
  messages,
  title,
  subtitle,
  showComposer,
  showHeader,
  className,
}: {
  messages: ChatMessageItem[];
  title?: string;
  subtitle?: string;
  showComposer: boolean;
  showHeader: boolean;
  className?: string;
}) {
  const bg = "#1E1F22";
  const fg = "#DBDEE1";
  const muted = "#949BA4";
  const iconBg = "#2B2D31";

  const groups = groupByAuthor(messages);

  return (
    <div
      className={cn("flex h-full flex-col", className)}
      style={{ background: bg, color: fg, fontFamily: DISCORD_STACK }}
    >
      {/* Channel header */}
      {showHeader && (
        <div
          className="flex shrink-0 items-center gap-2 px-3"
          style={{
            background: bg,
            height: 48,
            borderBottom: "1px solid rgba(0,0,0,0.4)",
            zIndex: 2,
          }}
        >
          <button
            type="button"
            aria-label="Back"
            className="flex cursor-pointer items-center justify-center rounded-full transition-colors hover:bg-white/[0.06]"
            style={{ width: 28, height: 28, color: fg }}
          >
            <svg
              width="20"
              height="20"
              viewBox="0 0 24 24"
              aria-hidden
              fill="none"
            >
              <path
                d="M14 6l-6 6 6 6"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </button>
          <span style={{ fontSize: 18, color: muted, marginLeft: 2 }}>#</span>
          <span
            style={{
              fontSize: 17,
              fontWeight: 700,
              color: "#FFFFFF",
              letterSpacing: "-0.01em",
            }}
          >
            {title ?? "general"}
          </span>
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            aria-hidden
            fill="none"
            style={{ marginLeft: 2, color: muted }}
          >
            <path
              d="M9 6l6 6-6 6"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          <div className="flex flex-1" />
          <button
            type="button"
            aria-label="Search"
            className="flex cursor-pointer items-center justify-center rounded-full transition-[filter] duration-150 hover:brightness-125 active:brightness-90"
            style={{ width: 32, height: 32, background: iconBg, color: muted }}
          >
            <svg
              width="16"
              height="16"
              viewBox="0 0 24 24"
              aria-hidden
              fill="none"
            >
              <circle
                cx="11"
                cy="11"
                r="7"
                stroke="currentColor"
                strokeWidth="2"
              />
              <path
                d="m20 20-4-4"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
              />
            </svg>
          </button>
        </div>
      )}
      <div
        className="flex flex-1 flex-col overflow-y-auto py-3"
        style={{ scrollbarWidth: "none", gap: 18 }}
      >
        {groups.map((g, gi) => (
          <div
            key={gi}
            className="chat-bubble-pop flex gap-3"
            style={{ padding: "0 12px" }}
          >
            <div
              className="shrink-0 overflow-hidden rounded-full"
              style={{
                width: 40,
                height: 40,
              }}
            >
              {/* biome-ignore lint/performance/noImgElement: avatar */}
              <img
                src={g.author?.avatar ?? DEFAULT_AVATAR}
                alt=""
                style={{
                  width: 40,
                  height: 40,
                  objectFit: "cover",
                  transform: "scale(1.05)",
                }}
              />
            </div>
            <div className="flex min-w-0 flex-1 flex-col">
              <div className="flex items-baseline gap-2">
                <span
                  style={{
                    fontWeight: 600,
                    fontSize: 15,
                    color: g.author?.color ?? "#FFFFFF",
                  }}
                >
                  {g.author?.name ?? "Unknown"}
                </span>
                <span style={{ fontSize: 12, color: muted }}>
                  Today at {g.items[0].time ?? ""}
                </span>
              </div>
              <div className="flex flex-col" style={{ gap: 4 }}>
                {g.items.map((m, i) => (
                  <div
                    key={m.id ?? `${gi}-${i}`}
                    style={{
                      fontSize: 15,
                      lineHeight: "1.375",
                      color: fg,
                      wordBreak: "break-word",
                      whiteSpace: "pre-wrap",
                    }}
                  >
                    {m.typing ? (
                      <TypingDots color={muted} />
                    ) : (
                      renderDiscordText(m.text ?? "")
                    )}
                  </div>
                ))}
              </div>
              {g.items.some((m) => m.reactions?.length) && (
                <div className="mt-1 flex flex-wrap gap-1">
                  {g.items.flatMap((m) =>
                    (m.reactions ?? []).map((r, ri) => (
                      <span
                        key={`${ri}-${r.emoji}`}
                        className="inline-flex items-center gap-1"
                        style={{
                          padding: "2px 7px",
                          borderRadius: 8,
                          border: "1px solid rgba(88,101,242,0.3)",
                          background: "rgba(88,101,242,0.15)",
                          fontSize: 13,
                          fontWeight: 600,
                          color: "#A8B6FF",
                        }}
                      >
                        <span>{r.emoji}</span>
                        {r.count}
                      </span>
                    )),
                  )}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
      {showComposer && (
        <div
          className="flex shrink-0 items-center gap-2 px-3 pt-2 pb-2"
          style={{ background: bg }}
        >
          <DiscordCircleButton bg={iconBg} fg={fg} label="Add">
            <svg
              width="20"
              height="20"
              viewBox="0 0 24 24"
              aria-hidden
              fill="none"
            >
              <path
                d="M12 5v14M5 12h14"
                stroke="currentColor"
                strokeWidth="2.4"
                strokeLinecap="round"
              />
            </svg>
          </DiscordCircleButton>
          <DiscordCircleButton bg={iconBg} fg={fg} label="Stickers">
            <DiscordStickerIcon size={20} />
          </DiscordCircleButton>
          <DiscordCircleButton bg={iconBg} fg="#5865F2" label="Gift">
            <DiscordGiftIcon size={20} />
          </DiscordCircleButton>
          <div
            className="flex flex-1 items-center"
            style={{
              background: iconBg,
              borderRadius: 20,
              padding: "0 12px",
              height: 36,
            }}
          >
            <input
              type="text"
              placeholder="Message"
              className="chat-demo-input min-w-0 flex-1 border-0 bg-transparent p-0 outline-none placeholder:text-[#949BA4]"
              style={{
                fontSize: 15,
                color: fg,
                fontFamily: "inherit",
              }}
            />
          </div>
          <DiscordCircleButton bg={iconBg} fg={fg} label="Voice">
            <MicIcon size={18} />
          </DiscordCircleButton>
        </div>
      )}
    </div>
  );
}

function DiscordCircleButton({
  bg,
  fg,
  label,
  children,
}: {
  bg: string;
  fg: string;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      className="flex shrink-0 cursor-pointer items-center justify-center rounded-full transition-[filter,opacity] duration-150 hover:brightness-125 active:brightness-90"
      style={{ width: 36, height: 36, background: bg, color: fg }}
    >
      {children}
    </button>
  );
}

function renderDiscordText(text: string) {
  const parts = text.split(/(@\w+|#\w+|`[^`]+`|:\w+:)/g);
  return parts.map((p, i) => {
    if (/^@\w+/.test(p)) {
      return (
        <span
          key={i}
          style={{
            background: "rgba(88,101,242,0.3)",
            color: "#C9CDFB",
            padding: "0 2px",
            borderRadius: 3,
            fontWeight: 500,
          }}
        >
          {p}
        </span>
      );
    }
    if (/^#\w+/.test(p)) {
      return (
        <span key={i} style={{ color: "#00A8FC", fontWeight: 500 }}>
          {p}
        </span>
      );
    }
    if (/^`[^`]+`$/.test(p)) {
      return (
        <code
          key={i}
          style={{
            background: "#2B2D31",
            borderRadius: 3,
            padding: "0 4px",
            fontFamily: '"Menlo", Consolas, monospace',
            fontSize: 13.6,
          }}
        >
          {p.slice(1, -1)}
        </code>
      );
    }
    return <span key={i}>{p}</span>;
  });
}

/* =========================================================================
 * Shared helpers
 * ========================================================================= */

function TypingDots({ color }: { color: string }) {
  return (
    <span
      aria-label="typing"
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        padding: "2px 0",
      }}
    >
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          style={{
            width: 6,
            height: 6,
            borderRadius: 9999,
            background: color,
            opacity: 0.6,
            animation: `chat-demo-typing 1.2s ${i * 0.15}s infinite ease-in-out`,
            display: "inline-block",
          }}
        />
      ))}
    </span>
  );
}

/* ----- Shared composer icons (user-provided paths) ----- */

function MicIcon({ size = 22 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      aria-hidden
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M19 10V12C19 15.866 15.866 19 12 19M5 10V12C5 15.866 8.13401 19 12 19M12 19V22M8 22H16M12 15C10.3431 15 9 13.6569 9 12V5C9 3.34315 10.3431 2 12 2C13.6569 2 15 3.34315 15 5V12C15 13.6569 13.6569 15 12 15Z" />
    </svg>
  );
}

function AttachmentIcon({ size = 22 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      aria-hidden
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M21.1525 10.8995L12.1369 19.9151C10.0866 21.9653 6.7625 21.9653 4.71225 19.9151C2.662 17.8648 2.662 14.5407 4.71225 12.4904L13.7279 3.47483C15.0947 2.108 17.3108 2.108 18.6776 3.47483C20.0444 4.84167 20.0444 7.05775 18.6776 8.42458L10.0156 17.0866C9.33213 17.7701 8.22409 17.7701 7.54068 17.0866C6.85726 16.4032 6.85726 15.2952 7.54068 14.6118L15.1421 7.01037" />
    </svg>
  );
}

function CameraIcon({ size = 22 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      aria-hidden
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M2 8.37722C2 8.0269 2 7.85174 2.01462 7.70421C2.1556 6.28127 3.28127 5.1556 4.70421 5.01462C4.85174 5 5.03636 5 5.40558 5C5.54785 5 5.61899 5 5.67939 4.99634C6.45061 4.94963 7.12595 4.46288 7.41414 3.746C7.43671 3.68986 7.45781 3.62657 7.5 3.5C7.54219 3.37343 7.56329 3.31014 7.58586 3.254C7.87405 2.53712 8.54939 2.05037 9.32061 2.00366C9.38101 2 9.44772 2 9.58114 2H14.4189C14.5523 2 14.619 2 14.6794 2.00366C15.4506 2.05037 16.126 2.53712 16.4141 3.254C16.4367 3.31014 16.4578 3.37343 16.5 3.5C16.5422 3.62657 16.5633 3.68986 16.5859 3.746C16.874 4.46288 17.5494 4.94963 18.3206 4.99634C18.381 5 18.4521 5 18.5944 5C18.9636 5 19.1483 5 19.2958 5.01462C20.7187 5.1556 21.8444 6.28127 21.9854 7.70421C22 7.85174 22 8.0269 22 8.37722V16.2C22 17.8802 22 18.7202 21.673 19.362C21.3854 19.9265 20.9265 20.3854 20.362 20.673C19.7202 21 18.8802 21 17.2 21H6.8C5.11984 21 4.27976 21 3.63803 20.673C3.07354 20.3854 2.6146 19.9265 2.32698 19.362C2 18.7202 2 17.8802 2 16.2V8.37722Z" />
      <path d="M12 16.5C14.2091 16.5 16 14.7091 16 12.5C16 10.2909 14.2091 8.5 12 8.5C9.79086 8.5 8 10.2909 8 12.5C8 14.7091 9.79086 16.5 12 16.5Z" />
    </svg>
  );
}

function DiscordStickerIcon({ size = 20 }: { size?: number }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 96 96"
      width={size}
      height={size}
      aria-hidden
    >
      <g transform="matrix(2.7,0,0,2.7,-79.6,-81.35)">
        <g transform="translate(32.022 32.647)">
          <g transform="translate(7.18 7.181)">
            <path
              fill="currentColor"
              d="M-6.555 1.641c-.375 1.401.455 2.84 1.856 3.216l6.34 1.698c1.4.376 2.841-.456 3.216-1.856L6.555-1.641C6.93-3.042 6.099-4.481 4.699-4.857L-1.641-6.556c-1.4-.375-2.841.457-3.216 1.857z"
            />
          </g>
        </g>
        <g transform="translate(47.443 32.419)">
          <g transform="translate(7.802 7.022)">
            <path
              fill="currentColor"
              d="M-6.478 2.404C-7.552 4.372-6.127 6.772-3.885 6.772h7.771c2.242 0 3.666-2.4 2.593-4.368L2.593-4.719c-1.119-2.053-4.066-2.053-5.186 0z"
            />
          </g>
        </g>
        <g transform="translate(32.12 49.045)">
          <g transform="translate(7.082 7.047)">
            <path
              fill="currentColor"
              d="M-.941-6.268c.52-.529 1.361-.529 1.882 0l1.116 1.135c.213.216.491.353.789.388l1.566.183c.729.085 1.254.756 1.173 1.501l-.174 1.598a1.4 1.4 0 0 0 .195.872l.836 1.363c.39.635.203 1.472-.419 1.872l-1.333.858a1.4 1.4 0 0 0-.547.699l-.523 1.517c-.243.706-1.001 1.079-1.695.833l-1.488-.529a1.32 1.32 0 0 0-.876 0l-1.489.529c-.693.246-1.451-.127-1.695-.833l-.523-1.517a1.4 1.4 0 0 0-.546-.699L-6.024 2.644c-.621-.4-.808-1.237-.419-1.872l.837-1.363a1.4 1.4 0 0 0 .194-.872l-.173-1.598c-.081-.745.443-1.416 1.173-1.501l1.565-.183c.299-.035.577-.172.79-.388z"
            />
          </g>
        </g>
        <g transform="matrix(-1,0,0,-1,62.694,63.32)">
          <g transform="translate(7.247 7.247)">
            <path
              fill="currentColor"
              d="M1.513-5.592C.993-6.997-.994-6.997-1.514-5.592l-.677 1.831c-.269.727-.843 1.301-1.571 1.57l-1.83.678c-1.405.52-1.405 2.506 0 3.026l1.83.678c.728.269 1.302.843 1.571 1.57l.677 1.831c.52 1.405 2.507 1.405 3.027 0l.677-1.831c.27-.727.843-1.301 1.571-1.57l1.832-.678c1.405-.52 1.405-2.506 0-3.026l-1.832-.678c-.728-.269-1.301-.843-1.571-1.57z"
            />
          </g>
        </g>
      </g>
    </svg>
  );
}

function DiscordGiftIcon({ size = 20 }: { size?: number }) {
  // Verbatim Lottie SVG provided by the user — transforms preserved as-is.
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      width={size}
      height={size}
      aria-hidden
    >
      <g transform="matrix(0.04,0,0,0.04,0,0)">
        <g transform="matrix(25,0,0,25,300,300)">
          <path
            fill="currentColor"
            d="M-7,10 C-8.105,10 -9,9.105 -9,8 V2.5 C-9,2.224 -8.776,2 -8.5,2 H-1.5 C-1.224,2 -1,2.224 -1,2.5 V9.5 C-1,9.776 -1.224,10 -1.5,10 Z M1,9.5 C1,9.776 1.224,10 1.5,10 H7 C8.105,10 9,9.105 9,8 V2.5 C9,2.224 8.776,2 8.5,2 H1.5 C1.224,2 1,2.224 1,2.5 Z"
          />
        </g>
        <g transform="matrix(25,0,0,25,300,300)">
          <path
            fill="currentColor"
            d="M-10,-2 C-10,-3.105 -9.105,-4 -8,-4 H8 C9.105,-4 10,-3.105 10,-2 V-0.5 C10,-0.224 9.776,0 9.5,0 H-9.5 C-9.776,0 -10,-0.224 -10,-0.5 Z"
          />
        </g>
        <g transform="matrix(25,0,0,25,300,300)">
          <path
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinejoin="round"
            d="M7,-6 C7,-7.657 5.657,-9 4,-9 H3.911 C2.494,-9 1.259,-8.036 0.915,-6.661 L0,-3 H4 C5.657,-3 7,-4.343 7,-6 Z"
          />
        </g>
        <g transform="matrix(25,0,0,25,300,300)">
          <path
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinejoin="round"
            d="M-7,-6 C-7,-7.657 -5.657,-9 -4,-9 H-3.911 C-2.494,-9 -1.259,-8.036 -0.915,-6.661 L0,-3 H-4 C-5.657,-3 -7,-4.343 -7,-6 Z"
          />
        </g>
      </g>
    </svg>
  );
}

function EmojiIcon({ size = 22 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      aria-hidden
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M8 14C8 14 9.5 16 12 16C14.5 16 16 14 16 14M15 9H15.01M9 9H9.01M22 12C22 17.5228 17.5228 22 12 22C6.47715 22 2 17.5228 2 12C2 6.47715 6.47715 2 12 2C17.5228 2 22 6.47715 22 12ZM15.5 9C15.5 9.27614 15.2761 9.5 15 9.5C14.7239 9.5 14.5 9.27614 14.5 9C14.5 8.72386 14.7239 8.5 15 8.5C15.2761 8.5 15.5 8.72386 15.5 9ZM9.5 9C9.5 9.27614 9.27614 9.5 9 9.5C8.72386 9.5 8.5 9.27614 8.5 9C8.5 8.72386 8.72386 8.5 9 8.5C9.27614 8.5 9.5 8.72386 9.5 9Z" />
    </svg>
  );
}

type AuthorGroup = {
  author?: { name: string; avatar?: string; color?: string };
  items: ChatMessageItem[];
};

function groupByAuthor(messages: ChatMessageItem[]): AuthorGroup[] {
  const out: AuthorGroup[] = [];
  for (const m of messages) {
    const last = out[out.length - 1];
    if (last && last.author?.name === m.author) {
      last.items.push(m);
    } else {
      out.push({
        author: {
          name: m.author ?? "Unknown",
          avatar: m.avatar,
          color: m.authorColor,
        },
        items: [m],
      });
    }
  }
  return out;
}
