import type { Metadata } from "next";
import { notFound } from "next/navigation";
import type { ComponentType } from "react";

import DiscordBotDemo from "@/features/landing/components/features/demos/DiscordBotDemo";
import SlackBotDemo from "@/features/landing/components/features/demos/SlackBotDemo";
import TelegramBotDemo from "@/features/landing/components/features/demos/TelegramBotDemo";
import WhatsAppBotDemo from "@/features/landing/components/features/demos/WhatsAppBotDemo";

const DEMOS: Record<string, ComponentType> = {
  discord: DiscordBotDemo,
  slack: SlackBotDemo,
  telegram: TelegramBotDemo,
  whatsapp: WhatsAppBotDemo,
};

export const metadata: Metadata = {
  robots: { index: false, follow: false },
};

export function generateStaticParams() {
  return Object.keys(DEMOS).map((platform) => ({ platform }));
}

interface Props {
  readonly params: Promise<{ readonly platform: string }>;
}

export default async function EmbedDemoPage({ params }: Props) {
  const { platform } = await params;
  const Demo = DEMOS[platform];
  if (!Demo) notFound();

  return (
    <main className="mx-auto flex min-h-dvh max-w-md items-center justify-center bg-transparent p-2">
      <div className="w-full">
        <Demo />
      </div>
    </main>
  );
}
