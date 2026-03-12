import type { Metadata } from "next";
import JsonLd from "@/components/seo/JsonLd";
import { BotsPage } from "@/features/bots";
import {
  generateBreadcrumbSchema,
  generatePageMetadata,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";

export const metadata: Metadata = generatePageMetadata({
  title: "Your AI, Where You Already Work",
  description:
    "Chat with GAIA on Discord, Telegram, Slack, and WhatsApp. Delegate tasks, get answers, and run workflows — without leaving the apps you already use.",
  path: "/bots",
  keywords: [
    "GAIA bots",
    "Discord bot",
    "Telegram bot",
    "Slack bot",
    "WhatsApp bot",
    "AI assistant bot",
    "GAIA Discord",
    "GAIA Telegram",
    "chat with AI",
    "messaging bot",
  ],
});

export default function Bots() {
  const webPageSchema = generateWebPageSchema(
    "GAIA Bot Integrations",
    "Chat with GAIA on Discord, Telegram, Slack, and WhatsApp.",
    `${siteConfig.url}/bots`,
    [
      { name: "Home", url: siteConfig.url },
      { name: "Bots", url: `${siteConfig.url}/bots` },
    ],
  );
  const breadcrumbSchema = generateBreadcrumbSchema([
    { name: "Home", url: siteConfig.url },
    { name: "Bots", url: `${siteConfig.url}/bots` },
  ]);

  return (
    <>
      <JsonLd data={[webPageSchema, breadcrumbSchema]} />
      <BotsPage />
    </>
  );
}
