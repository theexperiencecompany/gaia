import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { generateLocalizedPageMetadata } from "@/i18n/getAlternates";

export async function glossaryHubMetadata(locale: string): Promise<Metadata> {
  const t = await getTranslations({ locale, namespace: "glossary" });

  return generateLocalizedPageMetadata({
    title: t("hub_meta_title"),
    description: t("hub_meta_description"),
    path: "/learn",
    keywords: [
      "AI glossary",
      "AI terminology",
      "productivity glossary",
      "AI concepts explained",
      "automation glossary",
      "AI agent definition",
      "LangGraph explained",
      "MCP explained",
      "workflow automation glossary",
    ],
    locale,
  });
}
