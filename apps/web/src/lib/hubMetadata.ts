import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { generateLocalizedPageMetadata } from "@/i18n/getAlternates";
import { hubPagePath } from "@/lib/hubPagination";

/** The translated hubs whose namespaces carry hub_meta_* and hub_page_meta_* copy. */
type HubNamespace = "automate" | "comparisons" | "glossary";

interface HubMetadataInput {
  readonly namespace: HubNamespace;
  readonly hubPath: string;
  readonly keywords: readonly string[];
  readonly locale: string;
  /** 1 for the hub itself; a later page gets its own title, description and self-canonical. */
  readonly page: number;
  readonly totalPages: number;
}

/** Metadata for one page of a translated hub directory. */
export async function hubMetadata({
  namespace,
  hubPath,
  keywords,
  locale,
  page,
  totalPages,
}: HubMetadataInput): Promise<Metadata> {
  const t = await getTranslations({ locale, namespace });
  const counts = { page, total: totalPages };
  const isLaterPage = page > 1;

  return generateLocalizedPageMetadata({
    title: isLaterPage ? t("hub_page_meta_title", counts) : t("hub_meta_title"),
    description: isLaterPage
      ? t("hub_page_meta_description", counts)
      : t("hub_meta_description"),
    path: hubPagePath(hubPath, page),
    keywords: [...keywords],
    locale,
  });
}
