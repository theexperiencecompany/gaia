import type { Metadata } from "next";
import { hubMetadata } from "@/lib/hubMetadata";

const AUTOMATE_HUB_KEYWORDS = [
  "automate tools together",
  "tool automation combos",
  "Gmail Slack automation",
  "Notion Todoist automation",
  "GitHub Linear automation",
  "AI workflow automation",
  "connect two apps AI",
  "productivity tool automation",
];

export function automateHubMetadata(
  locale: string,
  page = 1,
  totalPages = 1,
): Promise<Metadata> {
  return hubMetadata({
    namespace: "automate",
    hubPath: "/automate",
    keywords: AUTOMATE_HUB_KEYWORDS,
    locale,
    page,
    totalPages,
  });
}
