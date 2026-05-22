"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import Image from "next/image";
import Link from "next/link";
import { BOTS, type BotConfig } from "../constants";

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
}: BotConfig) {
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
          {BOTS.map((bot) => (
            <BotCard key={bot.id} {...bot} />
          ))}
        </div>
      </section>
    </div>
  );
}
