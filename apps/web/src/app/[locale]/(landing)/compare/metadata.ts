import type { Metadata } from "next";
import { hubMetadata } from "@/lib/hubMetadata";

const COMPARISONS_HUB_KEYWORDS = [
  "GAIA comparisons",
  "AI assistant comparison",
  "ChatGPT alternative",
  "Zapier alternative",
  "n8n alternative",
  "Motion alternative",
  "AI productivity tools",
  "best AI assistant",
];

export function comparisonsHubMetadata(
  locale: string,
  page = 1,
  totalPages = 1,
): Promise<Metadata> {
  return hubMetadata({
    namespace: "comparisons",
    hubPath: "/compare",
    keywords: COMPARISONS_HUB_KEYWORDS,
    locale,
    page,
    totalPages,
  });
}
