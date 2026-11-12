import type { Metadata } from "next";
import { hubMetadata } from "@/lib/hubMetadata";

const GLOSSARY_HUB_KEYWORDS = [
  "AI glossary",
  "AI terminology",
  "productivity glossary",
  "AI concepts explained",
  "automation glossary",
  "AI agent definition",
  "LangGraph explained",
  "MCP explained",
  "workflow automation glossary",
];

export function glossaryHubMetadata(
  locale: string,
  page = 1,
  totalPages = 1,
): Promise<Metadata> {
  return hubMetadata({
    namespace: "glossary",
    hubPath: "/learn",
    keywords: GLOSSARY_HUB_KEYWORDS,
    locale,
    page,
    totalPages,
  });
}
