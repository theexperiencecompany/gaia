"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { ArrowRight01Icon } from "@icons";
import Image from "next/image";
import Link from "next/link";

import LargeHeader from "../shared/LargeHeader";

interface BotShowcase {
  icon: string;
  name: string;
  handle: string;
  tagline: string;
  conversation: { from: "user" | "gaia"; text: string }[];
  primaryAction: { label: string; href: string; external?: boolean };
  accent: string;
}

const bots: BotShowcase[] = [
  {
    icon: "/images/icons/macos/discord.webp",
    name: "Discord",
    handle: "#general",
    tagline: "Slash commands, @mentions, or DMs — across any server.",
    conversation: [
      { from: "user", text: "/gaia summarise today's standup thread" },
      {
        from: "gaia",
        text: "3 updates, 2 blockers. Aryan is waiting on API keys from you.",
      },
    ],
    primaryAction: {
      label: "Add to Server",
      href: "https://heygaia.io/discord-bot",
      external: true,
    },
    accent: "from-indigo-500/15 to-transparent",
  },
  {
    icon: "/images/icons/macos/telegram.webp",
    name: "Telegram",
    handle: "@heygaia_bot",
    tagline: "Open a chat. No setup, no group — just you and GAIA.",
    conversation: [
      { from: "user", text: "remind me to call mum at 7pm" },
      { from: "gaia", text: "Reminder set for today, 7:00 PM." },
    ],
    primaryAction: {
      label: "Start Chatting",
      href: "https://t.me/heygaia_bot",
      external: true,
    },
    accent: "from-sky-500/15 to-transparent",
  },
  {
    icon: "/images/icons/macos/slack.webp",
    name: "Slack",
    handle: "#product",
    tagline: "Delegate tasks and run workflows from inside your workspace.",
    conversation: [
      { from: "user", text: "@GAIA draft the Q2 launch checklist" },
      {
        from: "gaia",
        text: "Drafted 12 items across eng, marketing, and support. Sharing in thread.",
      },
    ],
    primaryAction: {
      label: "Add to Workspace",
      href: "/slack-bot",
    },
    accent: "from-fuchsia-500/15 to-transparent",
  },
  {
    icon: "/images/icons/macos/whatsapp.webp",
    name: "WhatsApp",
    handle: "+1 (276) 208-8737",
    tagline: "Already on your phone. No new app, no new habits.",
    conversation: [
      { from: "user", text: "what's on my calendar tomorrow?" },
      {
        from: "gaia",
        text: "4 meetings. First is the design review at 9:30 AM.",
      },
    ],
    primaryAction: {
      label: "Start Chatting",
      href: "https://wa.me/12762088737",
      external: true,
    },
    accent: "from-emerald-500/15 to-transparent",
  },
];

function ChatPreview({
  conversation,
}: {
  conversation: BotShowcase["conversation"];
}) {
  return (
    <div className="flex flex-col gap-1.5">
      {conversation.map((message, idx) => (
        <div
          key={`${message.from}-${idx}`}
          className={`flex ${message.from === "user" ? "justify-end" : "justify-start"}`}
        >
          <div
            className={`max-w-[85%] rounded-2xl px-3 py-1.5 text-xs leading-snug ${
              message.from === "user"
                ? "bg-primary text-black"
                : "bg-zinc-800 text-zinc-200"
            }`}
          >
            {message.text}
          </div>
        </div>
      ))}
    </div>
  );
}

function BotCard({
  icon,
  name,
  handle,
  tagline,
  conversation,
  primaryAction,
  accent,
}: BotShowcase) {
  return (
    <div className="group relative flex flex-col gap-4 overflow-hidden rounded-3xl bg-zinc-900/50 p-4 transition hover:bg-zinc-900">
      <div
        className={`pointer-events-none absolute inset-0 -z-0 bg-gradient-to-br ${accent} opacity-60`}
        aria-hidden
      />

      <div className="relative flex items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="relative h-11 w-11 shrink-0 transition duration-150 group-hover:-rotate-6 group-hover:scale-110">
            <Image src={icon} alt={name} fill className="object-contain" />
          </div>
          <div className="flex flex-col">
            <div className="flex items-center gap-2">
              <h3 className="font-medium text-white">{name}</h3>
              <Chip size="sm" variant="flat" color="success">
                Beta
              </Chip>
            </div>
            <span className="font-mono text-xs text-zinc-500">{handle}</span>
          </div>
        </div>
      </div>

      <p className="relative text-sm text-zinc-400">{tagline}</p>

      <div className="relative rounded-2xl bg-zinc-950/60 p-3 outline-1 outline-zinc-800">
        <ChatPreview conversation={conversation} />
      </div>

      <div className="relative mt-auto flex justify-end">
        <Button
          as={Link}
          href={primaryAction.href}
          target={primaryAction.external ? "_blank" : "_self"}
          rel={primaryAction.external ? "noopener noreferrer" : undefined}
          color="primary"
          size="sm"
          endContent={<ArrowRight01Icon width={14} />}
        >
          {primaryAction.label}
        </Button>
      </div>
    </div>
  );
}

const stackedIcons = [
  {
    src: "/images/icons/macos/discord.webp",
    alt: "Discord",
    rotate: "-rotate-12",
    z: "z-[1]",
  },
  {
    src: "/images/icons/macos/slack.webp",
    alt: "Slack",
    rotate: "-rotate-6",
    z: "z-[2]",
  },
  {
    src: "/images/icons/macos/telegram.webp",
    alt: "Telegram",
    rotate: "rotate-6",
    z: "z-[3]",
  },
  {
    src: "/images/icons/macos/whatsapp.webp",
    alt: "WhatsApp",
    rotate: "rotate-12",
    z: "z-[4]",
  },
];

export default function BotsShowcaseSection() {
  return (
    <section className="flex w-full flex-col items-center px-4 py-20 sm:px-6 lg:px-8">
      <div className="flex w-full max-w-7xl flex-col items-center gap-10 rounded-2xl bg-gradient-to-b from-zinc-900 to-zinc-950 px-4 py-10 outline-1 outline-zinc-900 sm:rounded-3xl sm:p-10 lg:rounded-4xl lg:p-14">
        <div className="flex -space-x-4">
          {stackedIcons.map((icon) => (
            <div
              key={icon.alt}
              className={`relative h-16 w-16 sm:h-20 sm:w-20 ${icon.rotate} ${icon.z} transition hover:-translate-y-2 hover:scale-110`}
            >
              <Image
                src={icon.src}
                alt={icon.alt}
                fill
                className="object-contain"
                loading="lazy"
              />
            </div>
          ))}
        </div>

        <LargeHeader
          headingText="Talk to GAIA anywhere"
          subHeadingText="Chat, delegate tasks, and get answers right inside Discord, Telegram, Slack, or WhatsApp. No new app to learn, no new window to open."
          centered
        />

        <div className="grid w-full grid-cols-1 gap-4 sm:grid-cols-2">
          {bots.map((bot) => (
            <BotCard key={bot.name} {...bot} />
          ))}
        </div>

        <Button
          as={Link}
          href="/bots"
          variant="flat"
          size="lg"
          endContent={<ArrowRight01Icon width={16} />}
        >
          See all bots
        </Button>
      </div>
    </section>
  );
}
