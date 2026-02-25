"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import Image from "next/image";
import Link from "next/link";
import { siteConfig } from "@/lib/seo";

interface BotCardProps {
  icon: string;
  name: string;
  description: string;
  badge: {
    label: string;
    color: "warning" | "success" | "primary" | "default" | "secondary";
  };
  primaryAction?: {
    label: string;
    href: string;
    external?: boolean;
  };
  secondaryAction?: {
    label: string;
    href: string;
    external?: boolean;
  };
}

const bots: BotCardProps[] = [
  {
    icon: "/images/icons/macos/discord.webp",
    name: "Discord",
    description:
      "Add GAIA to any server or chat one-on-one. Use slash commands, @mention in any channel, or DM for personal help.",
    badge: { label: "Beta", color: "success" },
    primaryAction: {
      label: "Add to Server",
      href: `${siteConfig.url}/discord-bot`,
      external: true,
    },
    secondaryAction: {
      label: "Join Community",
      href: "https://discord.heygaia.io",
      external: true,
    },
  },
  {
    icon: "/images/icons/macos/telegram.webp",
    name: "Telegram",
    description:
      "Just open a chat with @heygaia_bot and start talking. No setup, no group required — it's just you and GAIA.",
    badge: { label: "Beta", color: "success" },
    primaryAction: {
      label: "Start Chatting",
      href: "https://t.me/heygaia_bot",
      external: true,
    },
    secondaryAction: {
      label: "Read the Docs",
      href: "https://docs.heygaia.io/bots/telegram",
      external: true,
    },
  },
  {
    icon: "/images/icons/macos/slack.webp",
    name: "Slack",
    description:
      "Bring GAIA into your workspace. Delegate tasks, run workflows, and get answers — all inside Slack.",
    badge: { label: "Beta", color: "success" },
    primaryAction: {
      label: "Add to Workspace",
      href: "/slack-bot",
    },
  },
  {
    icon: "/images/icons/macos/whatsapp.webp",
    name: "WhatsApp",
    description:
      "Talk to GAIA on the app already on your phone. Ask questions, delegate tasks — no new accounts, no new habits.",
    badge: { label: "Coming Soon", color: "secondary" },
  },
];

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

function BotCard({
  icon,
  name,
  description,
  badge,
  primaryAction,
  secondaryAction,
}: BotCardProps) {
  return (
    <div className="flex flex-col items-start gap-5 rounded-3xl bg-zinc-900/50 p-4 text-left group hover:bg-zinc-900 transition">
      <div className="flex w-full items-start gap-2 flex-col">
        <div className="relative h-15 w-15 shrink-0 group-hover:scale-110 group-hover:-rotate-10 transition duration-100">
          <Image src={icon} alt={name} fill className="object-contain" />
        </div>
        <div className="flex items-center gap-2 justifybet">
          <h2 className="font-medium text-white text-xl">{name}</h2>
          <Chip size="sm" variant="flat" color={badge.color}>
            {badge.label}
          </Chip>
        </div>
        <p className="text-sm text-zinc-400">{description}</p>
      </div>
      <div className="flex flex-wrap items-center justify-end gap-2 w-full">
        {primaryAction && (
          <Button
            as={Link}
            href={primaryAction.href}
            target={primaryAction.external ? "_blank" : "_self"}
            rel={primaryAction.external ? "noopener noreferrer" : undefined}
            color="primary"
          >
            {primaryAction.label}
          </Button>
        )}
        {secondaryAction && (
          <Button
            as={Link}
            href={secondaryAction.href}
            target={secondaryAction.external ? "_blank" : "_self"}
            rel={secondaryAction.external ? "noopener noreferrer" : undefined}
            variant="flat"
          >
            {secondaryAction.label}
          </Button>
        )}
      </div>
    </div>
  );
}

export default function BotsPage() {
  return (
    <div className="relative flex min-h-screen w-full flex-col items-center">
      <section className="relative z-10 flex w-full max-w-5xl flex-col items-center gap-3 px-6 pb-8 pt-24 sm:pt-32">
        <div className="flex -space-x-4">
          {stackedIcons.map((icon) => (
            <div
              key={icon.alt}
              className={`relative h-20 w-20 ${icon.rotate} ${icon.z}`}
            >
              <Image
                src={icon.src}
                alt={icon.alt}
                fill
                className="object-contain hover:scale-110 hover:-translate-y-4 transition"
              />
            </div>
          ))}
        </div>
        <div className="flex flex-col items-center gap-3">
          <h1 className="mt-2 font-serif text-4xl font-medium text-white sm:text-6xl">
            Your AI, Where You Already Work
          </h1>
          <p className="max-w-xl text-center text-lg text-zinc-400">
            Chat, delegate tasks, and get answers — right inside Discord,
            Telegram, Slack, or WhatsApp.
          </p>
        </div>
      </section>

      <section className="relative z-10 mx-auto w-full max-w-3xl px-6 pb-16 gap-5 pt-4">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-2">
          {bots.map((bot) => (
            <BotCard key={bot.name} {...bot} />
          ))}
        </div>
      </section>
    </div>
  );
}
