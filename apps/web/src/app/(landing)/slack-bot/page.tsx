import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { generatePageMetadata } from "@/lib/seo";

export const metadata: Metadata = generatePageMetadata({
  title: "Add GAIA to Slack",
  description:
    "Add the GAIA AI assistant to your Slack workspace. Use slash commands to chat with GAIA, manage todos, and run workflows without leaving Slack.",
  path: "/slack-bot",
  keywords: [
    "GAIA Slack bot",
    "add Slack bot",
    "Slack AI assistant",
    "Slack bot install",
    "GAIA bot",
    "Slack slash commands",
  ],
});

const SLACK_CLIENT_ID = process.env.NEXT_PUBLIC_SLACK_CLIENT_ID;
const SLACK_SCOPES = [
  "chat:write",
  "commands",
  "im:history",
  "im:read",
  "im:write",
].join(",");

export default function SlackBotPage() {
  const url = new URL("https://slack.com/oauth/v2/authorize");
  url.searchParams.set("client_id", SLACK_CLIENT_ID ?? "");
  url.searchParams.set("scope", SLACK_SCOPES);

  redirect(url.toString());
}
