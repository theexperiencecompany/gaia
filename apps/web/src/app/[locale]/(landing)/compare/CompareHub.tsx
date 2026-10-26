import type { Metadata } from "next";
import Image from "next/image";
import { notFound } from "next/navigation";
import { getTranslations, setRequestLocale } from "next-intl/server";
import { HubPagination, HubSectionNav } from "@/components/seo/HubPageNav";
import JsonLd from "@/components/seo/JsonLd";
import { SiteLink } from "@/components/seo/SiteLink";
import { comparisonHubPages } from "@/features/comparisons/data/comparisonHubPages";
import { getAllComparisons } from "@/features/comparisons/data/comparisonsData";
import { getTranslatedComparisons } from "@/features/comparisons/data/getTranslatedComparison";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import { generateLocalizedPageMetadata } from "@/i18n/getAlternates";
import { hubPagePath } from "@/lib/hubPagination";
import {
  generateBreadcrumbSchema,
  generateItemListSchema,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";

const HUB_PATH = "/compare";

const HUB_KEYWORDS = [
  "GAIA comparisons",
  "AI assistant comparison",
  "ChatGPT alternative",
  "Zapier alternative",
  "n8n alternative",
  "Motion alternative",
  "AI productivity tools",
  "best AI assistant",
];

export async function generateCompareHubMetadata(
  locale: string,
  page: number,
): Promise<Metadata> {
  const [t, pages] = await Promise.all([
    getTranslations({ locale, namespace: "comparisons" }),
    getAllComparisons().then(comparisonHubPages),
  ]);
  return generateLocalizedPageMetadata({
    title:
      page === 1
        ? t("hub_meta_title")
        : t("hub_page_meta_title", { page, total: pages.length }),
    description:
      page === 1
        ? t("hub_meta_description")
        : t("hub_page_meta_description", { page, total: pages.length }),
    path: hubPagePath(HUB_PATH, page),
    keywords: HUB_KEYWORDS,
    locale,
  });
}

/** One page of the /compare hub: its categories' comparisons, the jump links to them, and links to every other page. */
export async function CompareHubPage({
  locale,
  page,
}: {
  readonly locale: string;
  readonly page: number;
}) {
  setRequestLocale(locale);
  const [t, tCommon, comparisons] = await Promise.all([
    getTranslations({ locale, namespace: "comparisons" }),
    getTranslations({ locale, namespace: "common" }),
    getTranslatedComparisons(locale),
  ]);
  const pages = comparisonHubPages(comparisons);
  const hubPage = pages.find((candidate) => candidate.page === page);
  if (!hubPage) notFound();

  const pageUrl = `${siteConfig.url}${hubPagePath(HUB_PATH, page)}`;
  const breadcrumbs = [
    { name: "Home", url: siteConfig.url },
    { name: t("breadcrumb"), url: `${siteConfig.url}${HUB_PATH}` },
    ...(page === 1
      ? []
      : [{ name: tCommon("page_label", { page }), url: pageUrl }]),
  ];

  const webPageSchema = generateWebPageSchema(
    t("hub_title"),
    t("hub_subtitle"),
    pageUrl,
    breadcrumbs,
  );
  const breadcrumbSchema = generateBreadcrumbSchema(breadcrumbs);
  const itemListSchema = generateItemListSchema(
    hubPage.sections.flatMap((section) =>
      section.items.map((c) => ({
        name: t("gaia_vs", { name: c.name }),
        url: `${siteConfig.url}/compare/${c.slug}`,
      })),
    ),
  );

  return (
    <>
      <JsonLd data={[webPageSchema, breadcrumbSchema, itemListSchema]} />

      <div className="mx-auto max-w-5xl px-6 pt-36 pb-24">
        <header className="mb-16 text-center">
          <h1 className="mb-4 font-serif text-5xl font-normal text-white md:text-6xl">
            {t("hub_title")}
          </h1>
          <p className="mx-auto max-w-2xl text-xl text-zinc-400">
            {t("hub_subtitle")}
          </p>
        </header>

        <HubSectionNav
          label={tCommon("section_nav_label")}
          sections={hubPage.sections}
        />

        {hubPage.sections.map((section) => (
          <div key={section.id} id={section.id} className="mb-14">
            <h2 className="mb-6 border-b border-zinc-700 pb-3 text-xl font-semibold text-zinc-300">
              {section.label}
            </h2>
            <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
              {section.items.map((comparison) => (
                <SiteLink
                  key={comparison.slug}
                  href={`/compare/${comparison.slug}`}
                  className="group flex flex-col gap-3 rounded-3xl bg-zinc-800 p-5 transition-colors hover:bg-zinc-700/50"
                >
                  <div className="flex items-center -space-x-2">
                    <div
                      className="relative flex h-9 w-9 items-center justify-center p-0"
                      style={{ rotate: "-9deg", zIndex: 1 }}
                    >
                      <Image
                        src="/images/logos/macos.webp"
                        alt="GAIA"
                        width={50}
                        height={50}
                      />
                    </div>
                    <div
                      className="relative flex h-8 w-8 items-center justify-center rounded-md overflow-hidden p-0"
                      style={{ rotate: "9deg", zIndex: 0 }}
                    >
                      <Image
                        src={`https://www.google.com/s2/favicons?domain=${comparison.domain}&sz=128`}
                        alt={comparison.name}
                        width={40}
                        height={40}
                        unoptimized
                      />
                    </div>
                  </div>
                  <h3 className="text-lg font-medium text-white transition-colors group-hover:text-primary">
                    {t("gaia_vs", { name: comparison.name })}
                  </h3>
                  <p className="text-sm text-zinc-500">{comparison.tagline}</p>
                  <p className="line-clamp-2 text-sm leading-relaxed text-zinc-400">
                    {comparison.description}
                  </p>
                </SiteLink>
              ))}
            </div>
          </div>
        ))}

        <HubPagination
          hubPath={HUB_PATH}
          current={page}
          total={pages.length}
          label={tCommon("pagination_label")}
          pageLabel={(n) => tCommon("page_label", { page: n })}
        />
      </div>

      <FinalSection />
    </>
  );
}
