import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { generateLocalizedPageMetadata } from "@/i18n/getAlternates";

export async function comparisonsHubMetadata(
  locale: string,
): Promise<Metadata> {
  const t = await getTranslations({ locale, namespace: "comparisons" });

  return generateLocalizedPageMetadata({
    title: t("hub_meta_title"),
    description: t("hub_meta_description"),
    path: "/compare",
    keywords: [
      "GAIA comparisons",
      "AI assistant comparison",
      "ChatGPT alternative",
      "Zapier alternative",
      "n8n alternative",
      "Motion alternative",
      "AI productivity tools",
      "best AI assistant",
    ],
    locale,
  });
}
