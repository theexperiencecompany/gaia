import type { Metadata } from "next";
import { notFound } from "next/navigation";

import type { ChatPlatform } from "@/features/landing/components/iphone/ChatDemo";
import { EmbedPlatformDemo } from "@/features/landing/components/iphone/EmbedPlatformDemo";

const EMBED_PLATFORMS: ChatPlatform[] = [
  "discord",
  "slack",
  "telegram",
  "whatsapp",
];

export const metadata: Metadata = {
  robots: { index: false, follow: false },
};

export function generateStaticParams() {
  return EMBED_PLATFORMS.map((platform) => ({ platform }));
}

interface Props {
  readonly params: Promise<{ readonly platform: string }>;
}

export default async function EmbedDemoPage({ params }: Props) {
  const { platform } = await params;
  if (!EMBED_PLATFORMS.includes(platform as ChatPlatform)) notFound();

  return (
    <main className="flex min-h-dvh items-start justify-center bg-transparent p-2">
      <EmbedPlatformDemo platformId={platform as ChatPlatform} />
    </main>
  );
}
