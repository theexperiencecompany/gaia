import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { generateLocalizedPageMetadata } from "@/i18n/getAlternates";

export async function automateHubMetadata(locale: string): Promise<Metadata> {
  const t = await getTranslations({ locale, namespace: "automate" });

  return generateLocalizedPageMetadata({
    title: t("hub_meta_title"),
    description: t("hub_meta_description"),
    path: "/automate",
    keywords: [
      "automate tools together",
      "tool automation combos",
      "Gmail Slack automation",
      "Notion Todoist automation",
      "GitHub Linear automation",
      "AI workflow automation",
      "connect two apps AI",
      "productivity tool automation",
    ],
    locale,
  });
}
