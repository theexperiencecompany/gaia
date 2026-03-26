import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { generatePageMetadata } from "@/lib/seo";

export const metadata: Metadata = generatePageMetadata({
  title: "Add GAIA to Discord",
  description:
    "Add the GAIA AI assistant bot to your Discord server. Use slash commands, @mentions, and DMs to chat with GAIA, manage todos, and run workflows without leaving Discord.",
  path: "/discord-bot",
  keywords: [
    "GAIA Discord bot",
    "add Discord bot",
    "Discord AI assistant",
    "Discord bot invite",
    "GAIA bot",
    "Discord slash commands",
  ],
});

const DISCORD_CLIENT_ID = process.env.NEXT_PUBLIC_DISCORD_CLIENT_ID;

export default function DiscordBotPage() {
  const url = new URL("https://discord.com/oauth2/authorize");
  url.searchParams.set("client_id", DISCORD_CLIENT_ID ?? "");
  url.searchParams.set("scope", "bot applications.commands");
  url.searchParams.set("permissions", "2048");

  redirect(url.toString());
}
