"use client";

import { Accordion, AccordionItem } from "@heroui/accordion";
import { Button } from "@heroui/button";
import { Input } from "@heroui/input";
import {
  AttachmentIcon,
  Call02Icon,
  Camera01Icon,
  Gif01Icon,
  GiftIcon,
  Happy01Icon,
  HappyIcon,
  Mic02Icon,
  MoreVerticalCircle01Icon,
  PlusSignIcon,
  Search01Icon,
  SentIcon,
  TextBoldIcon,
  Video01Icon,
} from "@icons";
import { AnimatePresence, useInView } from "motion/react";
import * as m from "motion/react-m";
import Image from "next/image";
import type React from "react";
import { useEffect, useRef, useState } from "react";
import { Link } from "@/i18n/navigation";

import LargeHeader from "../shared/LargeHeader";

// ─── Config ───────────────────────────────────────────────────────────────────

type PlatformId = "whatsapp" | "telegram" | "slack" | "discord";

const DURATION = 7000;
const TICK = 50;

const AVATAR_ARYAN = "https://github.com/aryanranderiya.png";
const AVATAR_DHRUV = "https://github.com/dhruv-maradiya.png";

const MOBILE_ICON = 20;
const SEND_BTN_ICON = 20;
const DESKTOP_ICON = 16;

interface ActionLink {
  label: string;
  href: string;
  external?: boolean;
}

interface Platform {
  id: PlatformId;
  name: string;
  icon: string;
  description: string;
  primaryAction: ActionLink;
  secondaryAction?: ActionLink;
}

const PLATFORMS: Platform[] = [
  {
    id: "whatsapp",
    name: "WhatsApp",
    icon: "/images/icons/macos/whatsapp.webp",
    description:
      "Already on your phone. Text GAIA like a friend — reminders, plans, quick answers, anything.",
    primaryAction: {
      label: "Message GAIA",
      href: "https://wa.me/12762088737",
      external: true,
    },
  },
  {
    id: "telegram",
    name: "Telegram",
    icon: "/images/icons/macos/telegram.webp",
    description:
      "One tap to @heygaia_bot. No setup, no groups, no follow-up. Just ask.",
    primaryAction: {
      label: "Message GAIA",
      href: "https://t.me/heygaia_bot",
      external: true,
    },
  },
  {
    id: "slack",
    name: "Slack",
    icon: "/images/icons/macos/slack.webp",
    description:
      "@GAIA in any channel. Summarise threads, draft docs, pull updates, without opening a new tab.",
    primaryAction: {
      label: "Install in Slack",
      href: "/slack-bot",
    },
  },
  {
    id: "discord",
    name: "Discord",
    icon: "/images/icons/macos/discord.webp",
    description:
      "/gaia from any server. Summarise standups, ship digests, DM answers, all without a browser.",
    primaryAction: {
      label: "Add to Your Server",
      href: "https://heygaia.io/discord-bot",
      external: true,
    },
  },
];

// ─── Avatars ──────────────────────────────────────────────────────────────────

function GaiaAvatar({ size = 36 }: { size?: number }) {
  return (
    <div
      className="relative shrink-0 overflow-hidden rounded-full"
      style={{ width: size, height: size }}
    >
      <Image
        src="/images/logos/logo_bg_grey.png"
        alt="GAIA"
        fill
        className="object-cover"
        sizes={`${size}px`}
      />
    </div>
  );
}

function RemoteAvatar({
  src,
  size = 36,
  alt,
  rounded = "full",
}: {
  src: string;
  size?: number;
  alt: string;
  rounded?: "full" | "md";
}) {
  return (
    <div
      className={`relative shrink-0 overflow-hidden bg-zinc-800 ${
        rounded === "full" ? "rounded-full" : "rounded-md"
      }`}
      style={{ width: size, height: size }}
    >
      <Image
        src={src}
        alt={alt}
        fill
        className="object-cover"
        sizes={`${size}px`}
        unoptimized
      />
    </div>
  );
}

// ─── Icon button (HeroUI) ─────────────────────────────────────────────────────

function IconBtn({
  children,
  colorClass = "text-zinc-300",
  ariaLabel,
}: {
  children: React.ReactNode;
  colorClass?: string;
  ariaLabel: string;
}) {
  // Plain native button — avoids HeroUI Button's default min-width / slot sizing
  // that makes icons overflow their containers. Same interactivity, zero overflow.
  return (
    <button
      type="button"
      aria-label={ariaLabel}
      className={`inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-transparent transition hover:bg-white/10 ${colorClass}`}
    >
      {children}
    </button>
  );
}

// ─── Chat bubble ──────────────────────────────────────────────────────────────

function DoubleTick({ color }: { color: string }) {
  return (
    <svg
      viewBox="0 0 16 12"
      width="14"
      height="11"
      fill="none"
      aria-hidden="true"
      style={{ display: "inline-block", verticalAlign: "middle" }}
    >
      <title>Double tick</title>
      <path
        d="M1 6.5L5 10.5L11 3.5"
        stroke={color}
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M5.5 6.5L9 10.5L15 3.5"
        stroke={color}
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

interface BubbleProps {
  side: "in" | "out";
  color: string;
  textColor?: string;
  time: string;
  tickColor?: string;
  doubleTick?: boolean;
  children: React.ReactNode;
}

function ChatBubble({
  side,
  color,
  textColor = "#fff",
  time,
  tickColor,
  doubleTick,
  children,
}: BubbleProps) {
  const isOut = side === "out";
  return (
    <div className={`flex ${isOut ? "justify-end" : "justify-start"}`}>
      <div
        className="max-w-[82%] rounded-2xl px-4 py-2 text-[15px] leading-[1.4]"
        style={{ backgroundColor: color, color: textColor }}
      >
        <span className="whitespace-pre-wrap">{children}</span>
        <span className="ml-2 inline-flex items-center gap-1 align-bottom text-[11px] opacity-70">
          {time}
          {isOut && tickColor && doubleTick && <DoubleTick color={tickColor} />}
        </span>
      </div>
    </div>
  );
}

// ─── Mention / command highlight ──────────────────────────────────────────────

function Mention({
  text,
  variant,
}: {
  text: string;
  variant: "slack" | "discord";
}) {
  const styles =
    variant === "slack"
      ? { backgroundColor: "rgba(29,155,209,0.18)", color: "#6CB9EE" }
      : { backgroundColor: "rgba(88,101,242,0.25)", color: "#C9CDFB" };
  return (
    <span className="rounded px-1 py-[1px] font-medium" style={styles}>
      {text}
    </span>
  );
}

// ─── HeroUI Input styled as a transparent message field ──────────────────────

function MessageInput({
  placeholder,
  textColor,
}: {
  placeholder: string;
  textColor: string;
}) {
  return (
    <Input
      type="text"
      placeholder={placeholder}
      variant="flat"
      size="sm"
      classNames={{
        base: "flex-1",
        mainWrapper: "h-auto",
        inputWrapper: [
          "h-auto min-h-0 bg-transparent shadow-none p-0",
          "group-data-[focus=true]:bg-transparent",
          "data-[hover=true]:bg-transparent",
        ],
        input: "text-[13px] placeholder:opacity-100",
      }}
      style={{ color: textColor }}
    />
  );
}

// ─── WhatsApp ─────────────────────────────────────────────────────────────────

function WhatsAppDemo() {
  return (
    <div
      className="relative flex h-full w-full flex-col overflow-hidden"
      style={{ backgroundColor: "#0A1014" }}
    >
      {/* Wallpaper overlay — kept low-opacity */}
      <div
        className="pointer-events-none absolute inset-0"
        style={{
          backgroundImage: "url('/images/wallpapers/whatsapp-tile-dark.png')",
          backgroundRepeat: "repeat",
          opacity: 0.15,
        }}
        aria-hidden
      />

      {/* header — distinct darker band with subtle bottom border */}
      <div
        className="relative flex shrink-0 items-center gap-3 px-4 py-3"
        style={{
          backgroundColor: "#1F2C34",
          borderBottom: "1px solid rgba(0,0,0,0.3)",
        }}
      >
        <GaiaAvatar size={38} />
        <div className="flex min-w-0 flex-1 flex-col leading-tight">
          <span className="truncate text-[14px] font-semibold text-white">
            GAIA
          </span>
          <span className="text-[11px] text-[#25D366]">online</span>
        </div>
        <IconBtn ariaLabel="Video call" colorClass="text-zinc-300">
          <Video01Icon width={MOBILE_ICON} />
        </IconBtn>
        <IconBtn ariaLabel="Voice call" colorClass="text-zinc-300">
          <Call02Icon width={MOBILE_ICON} />
        </IconBtn>
        <IconBtn ariaLabel="Menu" colorClass="text-zinc-300">
          <MoreVerticalCircle01Icon width={MOBILE_ICON} />
        </IconBtn>
      </div>

      {/* messages */}
      <div className="relative flex flex-1 flex-col gap-2 overflow-y-auto px-4 py-4">
        <div
          className="mx-auto mb-2 rounded-md px-2.5 py-1 text-[10px] font-medium text-zinc-300"
          style={{ backgroundColor: "rgba(24,34,41,0.9)" }}
        >
          TODAY
        </div>
        <ChatBubble
          side="out"
          color="#005C4B"
          time="09:14"
          tickColor="#53bdeb"
          doubleTick
        >
          what&apos;s on my plate tomorrow?
        </ChatBubble>
        <ChatBubble side="in" color="#1F2C34" time="09:14">
          Light day. Design review at 9:30, lunch with Sarah at 12, deep work
          2-5. Want me to block the afternoon?
        </ChatBubble>
        <ChatBubble
          side="out"
          color="#005C4B"
          time="09:15"
          tickColor="#53bdeb"
          doubleTick
        >
          yes, and email sarah to confirm lunch
        </ChatBubble>
        <ChatBubble side="in" color="#1F2C34" time="09:15">
          Blocked. Sent Sarah a confirm, Pico at noon, parking link attached.
        </ChatBubble>
        <ChatBubble side="in" color="#1F2C34" time="09:17">
          FYI your Friday SF flight moved to gate 42. I&apos;ll text the night
          before.
        </ChatBubble>
      </div>

      {/* input — inset floating bar so it isn't clipped by the demo's rounded corners */}
      <div
        className="relative mx-3 mb-3 flex shrink-0 items-center gap-2 rounded-2xl px-3 py-2"
        style={{ backgroundColor: "#131C21" }}
      >
        <div
          className="flex min-w-0 flex-1 items-center gap-1 rounded-full px-2 py-1.5"
          style={{ backgroundColor: "#2A3942" }}
        >
          <IconBtn ariaLabel="Emoji" colorClass="text-[#8696A0]">
            <Happy01Icon width={MOBILE_ICON} />
          </IconBtn>
          <MessageInput placeholder="Message" textColor="#D1D7DB" />
          <IconBtn ariaLabel="Attach" colorClass="text-[#8696A0]">
            <AttachmentIcon width={MOBILE_ICON} />
          </IconBtn>
          <IconBtn ariaLabel="Camera" colorClass="text-[#8696A0]">
            <Camera01Icon width={MOBILE_ICON} />
          </IconBtn>
        </div>
        <Button
          isIconOnly
          radius="full"
          aria-label="Send voice"
          className="h-10 w-10 min-w-0"
          style={{ backgroundColor: "#00A884" }}
        >
          <Mic02Icon width={SEND_BTN_ICON} className="text-white" />
        </Button>
      </div>
    </div>
  );
}

// ─── Telegram ─────────────────────────────────────────────────────────────────

function TelegramDemo() {
  return (
    <div
      className="relative flex h-full w-full flex-col overflow-hidden"
      style={{ backgroundColor: "#0E1621" }}
    >
      <div
        className="pointer-events-none absolute inset-0"
        style={{
          backgroundImage:
            "radial-gradient(circle, rgba(91,157,217,0.08) 1px, transparent 1px)",
          backgroundSize: "22px 22px",
        }}
        aria-hidden
      />

      {/* header */}
      <div
        className="relative flex shrink-0 items-center gap-3 px-4 py-3"
        style={{
          backgroundColor: "#17212B",
          borderBottom: "1px solid rgba(0,0,0,0.35)",
        }}
      >
        <GaiaAvatar size={38} />
        <div className="flex min-w-0 flex-1 flex-col leading-tight">
          <span className="text-[14px] font-semibold text-white">GAIA</span>
          <span className="text-[11px] text-[#64B5F6]">bot</span>
        </div>
        <IconBtn ariaLabel="Search" colorClass="text-[#64B5F6]">
          <Search01Icon width={MOBILE_ICON} />
        </IconBtn>
        <IconBtn ariaLabel="Menu" colorClass="text-[#64B5F6]">
          <MoreVerticalCircle01Icon width={MOBILE_ICON} />
        </IconBtn>
      </div>

      {/* messages */}
      <div className="relative flex flex-1 flex-col gap-2 overflow-y-auto px-4 py-4">
        <ChatBubble
          side="out"
          color="#2B5278"
          time="14:02"
          tickColor="#64B5F6"
          doubleTick
        >
          any P0s in the backlog?
        </ChatBubble>
        <ChatBubble side="in" color="#182533" time="14:02">
          Two. &apos;Payment webhook retries&apos; (Priya) and &apos;OAuth
          refresh&apos; (Dhruv). Both in progress, ETA Friday.
        </ChatBubble>
        <ChatBubble
          side="out"
          color="#2B5278"
          time="14:04"
          tickColor="#64B5F6"
          doubleTick
        >
          draft a status update for leadership
        </ChatBubble>
        <ChatBubble side="in" color="#182533" time="14:04">
          Drafted: shipped, in-flight, blockers, next week. Send as Friday
          update?
        </ChatBubble>
        <ChatBubble
          side="out"
          color="#2B5278"
          time="14:05"
          tickColor="#64B5F6"
          doubleTick
        >
          yep
        </ChatBubble>
        <ChatBubble side="in" color="#182533" time="14:05">
          Sent to #leadership. I&apos;ll ping you if anyone replies.
        </ChatBubble>
      </div>

      {/* input — inset floating bar so it isn't clipped by the demo's rounded corners */}
      <div
        className="relative mx-3 mb-3 flex shrink-0 items-center gap-2 rounded-2xl px-3 py-2"
        style={{ backgroundColor: "#17212B" }}
      >
        <IconBtn ariaLabel="Attach" colorClass="text-[#64B5F6]">
          <AttachmentIcon width={MOBILE_ICON} />
        </IconBtn>
        <div
          className="flex min-w-0 flex-1 items-center gap-1 rounded-full px-3 py-1.5"
          style={{ backgroundColor: "#242F3D" }}
        >
          <MessageInput placeholder="Message" textColor="#D1D7DB" />
          <IconBtn ariaLabel="Emoji" colorClass="text-zinc-500">
            <HappyIcon width={MOBILE_ICON} />
          </IconBtn>
        </div>
        <Button
          isIconOnly
          radius="full"
          aria-label="Send voice"
          className="h-10 w-10 min-w-0"
          style={{ backgroundColor: "#2B5278" }}
        >
          <Mic02Icon width={SEND_BTN_ICON} className="text-white" />
        </Button>
      </div>
    </div>
  );
}

// ─── Server / workspace logos ────────────────────────────────────────────────

interface ServerLogo {
  name: string;
  src: string;
  bg?: string;
  padding?: number;
}

// Elevated grey relative to each platform's rail color.
const SLACK_GAIA_TILE_BG = "#2A2830"; // lifts above rail #19171D
const DISCORD_GAIA_TILE_BG = "#3A3C43"; // lifts above rail #1E1F22

const SLACK_WORKSPACES: ServerLogo[] = [
  {
    name: "GAIA",
    src: "/brand/gaia_logo.png",
    bg: SLACK_GAIA_TILE_BG,
    padding: 0.22,
  },
  { name: "Linear", src: "/images/icons/linear.svg", padding: 0.18 },
  { name: "Notion", src: "/images/icons/notion.webp", padding: 0.1 },
  {
    name: "Vercel",
    src: "/images/icons/vercel.svg",
    bg: "#000",
    padding: 0.22,
  },
];

const DISCORD_SERVERS: ServerLogo[] = [
  {
    name: "Discord",
    // Canonical Discord blurple with white Simple Icons logo.
    src: "https://cdn.simpleicons.org/discord/ffffff",
    bg: "#5865F2",
    padding: 0.2,
  },
  {
    name: "GAIA",
    src: "/brand/gaia_logo.png",
    bg: DISCORD_GAIA_TILE_BG,
    padding: 0.22,
  },
  { name: "Linear", src: "/images/icons/linear.svg", padding: 0.18 },
  { name: "Notion", src: "/images/icons/notion.webp", padding: 0.1 },
  {
    name: "Vercel",
    src: "/images/icons/vercel.svg",
    bg: "#000",
    padding: 0.22,
  },
];

function ServerTile({
  logo,
  size,
  radius,
}: {
  logo: ServerLogo;
  size: number;
  radius: number;
}) {
  const pad = Math.round(size * (logo.padding ?? 0.15));
  return (
    <div className="relative flex items-center">
      <Button
        isIconOnly
        radius="none"
        aria-label={logo.name}
        className="min-w-0 shrink-0 overflow-hidden p-0"
        style={{
          width: size,
          height: size,
          borderRadius: radius,
          backgroundColor: logo.bg ?? "#2B2D31",
        }}
      >
        <div
          className="absolute inset-0 flex items-center justify-center"
          style={{ padding: pad }}
        >
          <div className="relative h-full w-full">
            <Image
              src={logo.src}
              alt={logo.name}
              fill
              className="object-contain"
              sizes={`${size}px`}
            />
          </div>
        </div>
      </Button>
    </div>
  );
}

// ─── Slack ────────────────────────────────────────────────────────────────────

const SLACK_BORDER = "rgba(255,255,255,0.06)";

function SlackMessage({
  who,
  avatarSrc,
  color,
  time,
  children,
  isBot,
}: {
  who: string;
  avatarSrc?: string;
  color: string;
  time: string;
  children: React.ReactNode;
  isBot?: boolean;
}) {
  return (
    <div className="flex items-start gap-3">
      {isBot ? (
        <div className="overflow-hidden rounded-md">
          <GaiaAvatar size={36} />
        </div>
      ) : (
        <RemoteAvatar src={avatarSrc ?? ""} size={36} alt={who} rounded="md" />
      )}
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-1.5">
          <span
            className="text-[13px] font-bold leading-none"
            style={{ color }}
          >
            {who}
          </span>
          {isBot && (
            <span className="rounded-sm bg-white/10 px-1 py-[1px] text-[9px] font-semibold uppercase tracking-wide text-zinc-300">
              APP
            </span>
          )}
          <span className="text-[10.5px] leading-none text-zinc-500">
            {time}
          </span>
        </div>
        <p className="mt-1 text-[13px] leading-snug text-zinc-200">
          {children}
        </p>
      </div>
    </div>
  );
}

function SlackDemo() {
  return (
    <div
      className="relative flex h-full w-full overflow-hidden"
      style={{ backgroundColor: "#1A1D21" }}
    >
      {/* workspace rail */}
      <div
        className="flex w-[72px] shrink-0 flex-col items-center gap-3 px-2 py-3"
        style={{ backgroundColor: "#19171D" }}
      >
        {SLACK_WORKSPACES.map((logo) => (
          <ServerTile key={logo.name} logo={logo} size={40} radius={10} />
        ))}
      </div>

      {/* main */}
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <div
          className="flex h-12 shrink-0 items-center justify-between px-4"
          style={{ borderBottom: `1px solid ${SLACK_BORDER}` }}
        >
          <div className="flex items-center gap-2">
            <span className="text-[14px] font-bold text-white"># product</span>
            <span className="text-[11px] text-zinc-500">| 14</span>
          </div>
          <div className="flex items-center gap-1 text-zinc-400">
            <IconBtn ariaLabel="Start call">
              <Call02Icon width={DESKTOP_ICON} />
            </IconBtn>
            <IconBtn ariaLabel="Search">
              <Search01Icon width={DESKTOP_ICON} />
            </IconBtn>
          </div>
        </div>

        <div className="flex flex-1 flex-col gap-4 overflow-y-auto p-4">
          <SlackMessage
            who="dhruv"
            avatarSrc={AVATAR_DHRUV}
            color="#ECB22E"
            time="10:38 AM"
          >
            anyone got bandwidth to pull the Q2 launch checklist together?
          </SlackMessage>
          <SlackMessage
            who="aryan"
            avatarSrc={AVATAR_ARYAN}
            color="#36C5F0"
            time="10:40 AM"
          >
            <Mention text="@GAIA" variant="slack" /> take a crack at it from the
            meeting notes
          </SlackMessage>
          <SlackMessage who="GAIA" color="#E01E5A" time="10:40 AM" isBot>
            Drafted. 12 items across eng, design, marketing. 2 at risk: legal
            review pending, API keys blocked. Thread open for owner assignment.
          </SlackMessage>
        </div>

        <div
          className="m-3 shrink-0 overflow-hidden rounded-lg border border-white/10"
          style={{ backgroundColor: "#222529" }}
        >
          <div
            className="flex items-center gap-3 px-3 py-2 text-zinc-400"
            style={{ borderBottom: `1px solid ${SLACK_BORDER}` }}
          >
            <TextBoldIcon width={DESKTOP_ICON} />
            <span className="text-[13px] italic leading-none">i</span>
            <span className="text-[13px] line-through leading-none">S</span>
          </div>
          <div className="flex items-center justify-between gap-2 px-3 py-2">
            <MessageInput placeholder="Message #product" textColor="#D1D7DB" />
            <div className="flex shrink-0 items-center gap-1 text-zinc-500">
              <IconBtn ariaLabel="Attach">
                <AttachmentIcon width={DESKTOP_ICON} />
              </IconBtn>
              <IconBtn ariaLabel="Emoji">
                <HappyIcon width={DESKTOP_ICON} />
              </IconBtn>
              <IconBtn ariaLabel="Send">
                <SentIcon width={DESKTOP_ICON} />
              </IconBtn>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Discord ──────────────────────────────────────────────────────────────────

const DISCORD_BORDER = "rgba(0,0,0,0.35)";
const DISCORD_HEADER_HEIGHT = 48;

function DiscordMessage({
  who,
  avatarSrc,
  color,
  time,
  children,
  isBot,
}: {
  who: string;
  avatarSrc?: string;
  color: string;
  time: string;
  children: React.ReactNode;
  isBot?: boolean;
}) {
  return (
    <div className="flex items-start gap-3">
      {isBot ? (
        <GaiaAvatar size={38} />
      ) : (
        <RemoteAvatar src={avatarSrc ?? ""} size={38} alt={who} />
      )}
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-1.5">
          <span
            className="text-[14px] font-semibold leading-none"
            style={{ color }}
          >
            {who}
          </span>
          {isBot && (
            <span className="rounded bg-indigo-500 px-1 py-[2px] text-[9px] font-bold uppercase tracking-wide text-white">
              Bot
            </span>
          )}
          <span className="text-[10.5px] leading-none text-zinc-500">
            {time}
          </span>
        </div>
        <p className="mt-1 text-[13.5px] leading-snug text-zinc-200">
          {children}
        </p>
      </div>
    </div>
  );
}

function DiscordDemo() {
  return (
    <div
      className="relative flex h-full w-full overflow-hidden"
      style={{ backgroundColor: "#313338" }}
    >
      {/* server rail */}
      <div
        className="flex w-[80px] shrink-0 flex-col items-center gap-2.5 px-2 py-3"
        style={{ backgroundColor: "#1E1F22" }}
      >
        {DISCORD_SERVERS.map((logo) => (
          <ServerTile key={logo.name} logo={logo} size={46} radius={15} />
        ))}
      </div>

      {/* main */}
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <div
          className="flex shrink-0 items-center justify-between px-4"
          style={{
            height: DISCORD_HEADER_HEIGHT,
            borderBottom: `1px solid ${DISCORD_BORDER}`,
          }}
        >
          <div className="flex items-center gap-1.5">
            <span className="text-zinc-400">#</span>
            <span className="text-[14px] font-semibold text-white">
              general
            </span>
          </div>
          <IconBtn ariaLabel="Search">
            <Search01Icon width={DESKTOP_ICON} />
          </IconBtn>
        </div>

        <div className="flex flex-1 flex-col gap-5 overflow-y-auto p-4">
          <DiscordMessage
            who="aryan"
            avatarSrc={AVATAR_ARYAN}
            color="#F2B544"
            time="Today at 09:02"
          >
            <Mention text="/gaia" variant="discord" /> post yesterday&apos;s PR
            digest
          </DiscordMessage>
          <DiscordMessage
            who="GAIA"
            color="#8B5CF6"
            time="Today at 09:02"
            isBot
          >
            8 PRs shipped, 3 merged, 2 awaiting review.{" "}
            <Mention text="@dhruv" variant="discord" /> your billing-fix is
            still open.
          </DiscordMessage>
          <DiscordMessage
            who="dhruv"
            avatarSrc={AVATAR_DHRUV}
            color="#4ADE80"
            time="Today at 09:05"
          >
            <Mention text="@GAIA" variant="discord" /> ping me when mine gets
            reviewed
          </DiscordMessage>
          <DiscordMessage
            who="GAIA"
            color="#8B5CF6"
            time="Today at 09:05"
            isBot
          >
            Got it. I&apos;ll DM you the moment a reviewer approves.
          </DiscordMessage>
        </div>

        {/* composer — brighter shade so it lifts off the chat bg */}
        <div
          className="m-3 flex shrink-0 items-center gap-3 rounded-2xl px-3 py-2.5"
          style={{
            backgroundColor: "#434651",
            border: "1px solid rgba(0,0,0,0.35)",
          }}
        >
          <button
            type="button"
            aria-label="Attach"
            className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-zinc-300 hover:bg-white"
          >
            <PlusSignIcon width={DESKTOP_ICON - 2} className="text-zinc-800" />
          </button>
          <MessageInput placeholder="Message #general" textColor="#DBDEE1" />
          <div className="flex shrink-0 items-center gap-0.5 text-zinc-400">
            <IconBtn ariaLabel="Send gift" colorClass="text-zinc-400">
              <GiftIcon width={DESKTOP_ICON} />
            </IconBtn>
            <IconBtn ariaLabel="GIF" colorClass="text-zinc-400">
              <Gif01Icon width={DESKTOP_ICON} />
            </IconBtn>
            <IconBtn ariaLabel="Emoji" colorClass="text-zinc-400">
              <HappyIcon width={DESKTOP_ICON} />
            </IconBtn>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Demo container ───────────────────────────────────────────────────────────

const DEMO_MAP: Record<PlatformId, React.ComponentType> = {
  whatsapp: WhatsAppDemo,
  telegram: TelegramDemo,
  slack: SlackDemo,
  discord: DiscordDemo,
};

function PlatformDemo({ activeId }: { activeId: PlatformId }) {
  const Demo = DEMO_MAP[activeId];
  return (
    <div className="mx-auto w-full max-w-[640px]">
      <div
        className="relative w-full overflow-hidden rounded-2xl shadow-2xl shadow-black/40"
        style={{ aspectRatio: "5 / 4" }}
      >
        <AnimatePresence mode="wait">
          <m.div
            key={activeId}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.3, ease: [0.4, 0, 0.2, 1] }}
            className="absolute inset-0"
          >
            <Demo />
          </m.div>
        </AnimatePresence>
      </div>
    </div>
  );
}

// ─── Accordion sidebar (HeroUI) ──────────────────────────────────────────────

function PlatformAccordion({
  activeId,
  progress,
  onSelect,
}: {
  activeId: PlatformId;
  progress: number;
  onSelect: (id: PlatformId) => void;
}) {
  return (
    <div className="flex flex-col">
      <Accordion
        selectionMode="single"
        selectedKeys={new Set([activeId])}
        onSelectionChange={(keys) => {
          if (keys === "all") return;
          const next = [...keys][0] as PlatformId | undefined;
          if (next) onSelect(next);
        }}
        disallowEmptySelection
        showDivider={false}
        itemClasses={{
          base: "!shadow-none",
          trigger: "py-2 cursor-pointer",
          title: "text-[inherit]",
          content: "-mt-1 pb-6",
        }}
      >
        {PLATFORMS.map((platform, idx) => {
          const isActive = activeId === platform.id;
          const isLast = idx === PLATFORMS.length - 1;
          return (
            <AccordionItem
              key={platform.id}
              aria-label={platform.name}
              classNames={{
                // Single border-top per item, plus border-bottom only on the last.
                base: `relative !shadow-none border-t border-white/10 ${
                  isLast ? "border-b" : ""
                }`,
              }}
              title={
                <div className="flex items-center gap-4 py-1">
                  <Image
                    src={platform.icon}
                    alt={platform.name}
                    width={48}
                    height={48}
                    className="shrink-0 object-contain"
                  />
                  <span
                    className={`text-xl font-medium tracking-tight transition-colors ${
                      isActive ? "text-white" : "text-zinc-400"
                    }`}
                  >
                    {platform.name}
                  </span>
                </div>
              }
            >
              <p className="text-sm font-light leading-relaxed text-zinc-400">
                {platform.description}
              </p>
              <div className="mt-6 flex flex-wrap items-center justify-end gap-2">
                {platform.secondaryAction && (
                  <Button
                    as={Link}
                    href={platform.secondaryAction.href}
                    target={
                      platform.secondaryAction.external ? "_blank" : "_self"
                    }
                    rel={
                      platform.secondaryAction.external
                        ? "noopener noreferrer"
                        : undefined
                    }
                    variant="flat"
                  >
                    {platform.secondaryAction.label}
                  </Button>
                )}
                <Button
                  as={Link}
                  href={platform.primaryAction.href}
                  target={platform.primaryAction.external ? "_blank" : "_self"}
                  rel={
                    platform.primaryAction.external
                      ? "noopener noreferrer"
                      : undefined
                  }
                  color="primary"
                >
                  {platform.primaryAction.label}
                </Button>
              </div>
              {/* Progress bar: top edge of the open item, overlays the divider */}
              <div className="absolute left-0 right-0 top-0 h-[2px] w-full -translate-y-px overflow-hidden bg-transparent">
                <div
                  className="h-full bg-primary transition-none"
                  style={{ width: `${progress}%` }}
                />
              </div>
            </AccordionItem>
          );
        })}
      </Accordion>
    </div>
  );
}

// ─── Section ──────────────────────────────────────────────────────────────────

export default function BotsShowcaseSection() {
  const [activeId, setActiveId] = useState<PlatformId>("whatsapp");
  const [progress, setProgress] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);
  const isInView = useInView(containerRef, { once: true, amount: 0.2 });
  const stateRef = useRef({ activeId: "whatsapp" as PlatformId, elapsed: 0 });

  const handleSelect = (id: PlatformId) => {
    stateRef.current.activeId = id;
    stateRef.current.elapsed = 0;
    setActiveId(id);
    setProgress(0);
  };

  useEffect(() => {
    if (!isInView) return;
    const interval = setInterval(() => {
      stateRef.current.elapsed += TICK;
      const p = Math.min((stateRef.current.elapsed / DURATION) * 100, 100);
      setProgress(p);
      if (stateRef.current.elapsed >= DURATION) {
        stateRef.current.elapsed = 0;
        const currentIdx = PLATFORMS.findIndex(
          (pl) => pl.id === stateRef.current.activeId,
        );
        const next = PLATFORMS[(currentIdx + 1) % PLATFORMS.length].id;
        stateRef.current.activeId = next;
        setActiveId(next);
        setProgress(0);
      }
    }, TICK);
    return () => clearInterval(interval);
  }, [isInView]);

  return (
    <section
      ref={containerRef}
      className="flex w-full flex-col items-center px-4 py-24 sm:px-6 sm:py-28 lg:px-8 lg:py-32 min-h-screen justify-center my-20"
    >
      <div className="flex w-full max-w-7xl flex-col items-center gap-16">
        <div className="flex flex-col items-center text-center">
          <LargeHeader headingText="Reach GAIA from anywhere" centered />
          <p className="mt-2 max-w-[960px] text-base font-light text-zinc-400 sm:text-xl">
            Text it on WhatsApp. Mention it in Slack. Slash-command it in
            Discord. Same assistant, same memory, every channel you already live
            in.
          </p>
        </div>

        <div className="relative mx-auto flex w-full flex-col gap-10 px-2 lg:flex-row lg:items-stretch lg:gap-12 lg:px-4">
          <div className="w-full lg:w-1/2">
            <PlatformDemo activeId={activeId} />
          </div>
          <div className="flex w-full flex-col justify-center lg:w-1/2">
            <PlatformAccordion
              activeId={activeId}
              progress={progress}
              onSelect={handleSelect}
            />
          </div>
        </div>
      </div>
    </section>
  );
}
