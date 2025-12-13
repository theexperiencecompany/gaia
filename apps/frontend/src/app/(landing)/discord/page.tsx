import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { generatePageMetadata } from "@/lib/seo";

export const metadata: Metadata = generatePageMetadata({
  title: "Join Our Discord Community",
  description:
    "Join the GAIA Discord community to connect with other users, get support, share ideas, and stay updated with the latest features and announcements. Chat with the team and fellow members.",
  path: "/discord",
  keywords: [
    "GAIA Discord",
    "Discord community",
    "Discord server",
    "community support",
    "user community",
    "Discord chat",
    "join Discord",
    "GAIA community",
  ],
});

export default function DiscordPage() {
  redirect("https://discord.heygaia.io");
}
