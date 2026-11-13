"use client";

import Image from "next/image";
import Link from "next/link";
import { LinkButton } from "@/components/shared/LinkButton";
import CopyButton from "@/components/ui/CopyButton";
import { BOT_PLATFORM_ICONS } from "@/config/botPlatforms";
import type { BotConfig } from "../constants";
import { useBotCards } from "../hooks/useBotCards";
import { BOT_PLATFORM_REACH } from "../pageContent";
import BotsGuide from "./BotsGuide";

const stackedIcons = [
  {
    src: BOT_PLATFORM_ICONS.discord,
    rotate: "-rotate-12",
    z: "z-[1]",
  },
  {
    src: BOT_PLATFORM_ICONS.slack,
    rotate: "-rotate-6",
    z: "z-[2]",
  },
  {
    src: BOT_PLATFORM_ICONS.imessage,
    rotate: "rotate-0",
    z: "z-[3]",
  },
  {
    src: BOT_PLATFORM_ICONS.telegram,
    rotate: "rotate-6",
    z: "z-[4]",
  },
  {
    src: BOT_PLATFORM_ICONS.whatsapp,
    rotate: "rotate-12",
    z: "z-[5]",
  },
];

function BotCard({
  id,
  icon,
  name,
  description,
  primaryAction,
  secondaryAction,
  setupCommand,
}: BotConfig) {
  return (
    <div className="@container flex flex-col items-start gap-5 rounded-3xl bg-zinc-900/50 p-4 text-left group hover:bg-zinc-900 transition">
      <div className="flex w-full items-start gap-2 flex-col">
        <div className="relative h-15 w-15 shrink-0 group-hover:scale-110 group-hover:-rotate-10 transition duration-100">
          <Image
            src={icon}
            alt=""
            width={256}
            height={256}
            className="h-full w-full object-contain"
          />
        </div>
        <h2 className="font-medium text-white text-xl">{name}</h2>
        <p className="text-sm text-zinc-400">{description}</p>
        <p className="text-sm text-zinc-500">{BOT_PLATFORM_REACH[id]}</p>
      </div>
      {setupCommand && (
        <div className="flex w-full flex-col gap-2">
          <p className="text-sm text-zinc-500">
            Not set up on this instance. On the server, run:
          </p>
          <div className="flex w-full items-center gap-2 rounded-lg bg-zinc-800 py-1 pr-1 pl-3 text-zinc-200">
            <code className="min-w-0 flex-1 truncate font-mono text-xs">
              {setupCommand}
            </code>
            <CopyButton textToCopy={setupCommand} variant="ghost" />
          </div>
        </div>
      )}
      <div className="flex w-full flex-col gap-2 @min-[22rem]:flex-row @min-[22rem]:justify-end">
        {primaryAction && (
          <LinkButton
            href={primaryAction.href}
            target={primaryAction.external ? "_blank" : "_self"}
            rel={primaryAction.external ? "noopener noreferrer" : undefined}
            className="w-full @min-[22rem]:w-auto"
            variant="primary"
          >
            {primaryAction.label}
          </LinkButton>
        )}
        {secondaryAction && (
          <LinkButton
            href={secondaryAction.href}
            target={secondaryAction.external ? "_blank" : "_self"}
            rel={secondaryAction.external ? "noopener noreferrer" : undefined}
            variant="default-soft"
            className="w-full @min-[22rem]:w-auto"
          >
            {secondaryAction.label}
          </LinkButton>
        )}
      </div>
    </div>
  );
}

export default function BotsPage() {
  const bots = useBotCards();
  return (
    <div className="relative flex min-h-screen w-full flex-col items-center">
      <section className="relative z-10 flex w-full max-w-5xl flex-col items-center gap-3 px-6 pb-8 pt-24 sm:pt-32">
        <div className="flex -space-x-4">
          {stackedIcons.map((icon) => (
            <div
              key={icon.src}
              className={`relative h-20 w-20 ${icon.rotate} ${icon.z}`}
            >
              <Image
                src={icon.src}
                alt=""
                width={256}
                height={256}
                className="h-full w-full object-contain hover:scale-110 hover:-translate-y-4 transition"
              />
            </div>
          ))}
        </div>
        <div className="flex flex-col items-center gap-3">
          <h1 className="mt-2 text-center font-serif text-4xl font-medium text-white sm:text-6xl">
            Your AI, Where You Already Work
          </h1>
          <p className="max-w-xl text-center text-lg text-zinc-400">
            Chat, delegate tasks, and get answers, right inside Discord,
            Telegram, Slack, WhatsApp, or iMessage.
          </p>
          <Link
            href="/ai-assistant-whatsapp-telegram-imessage"
            className="text-sm text-zinc-500 underline underline-offset-2 hover:text-zinc-300"
          >
            What GAIA can do on WhatsApp, Telegram and iMessage
          </Link>
        </div>
      </section>

      <section className="relative z-10 mx-auto flex w-full max-w-4xl flex-col gap-10 px-6 pb-16 pt-4">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-2">
          {bots.map((bot) => (
            <BotCard key={bot.id} {...bot} />
          ))}
        </div>
        <BotsGuide />
      </section>
    </div>
  );
}
