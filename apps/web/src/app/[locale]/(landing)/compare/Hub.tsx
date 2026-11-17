import { getTranslations, setRequestLocale } from "next-intl/server";
import { HubPagination } from "@/components/seo/HubPagination";
import JsonLd from "@/components/seo/JsonLd";
import { SiteLink } from "@/components/seo/SiteLink";
import {
  comparisonCategoryGroups,
  comparisonCategoryPath,
} from "@/features/comparisons/data/comparisonCategories";
import { getTranslatedComparisons } from "@/features/comparisons/data/getTranslatedComparison";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import { hubPageCount, hubPageSlice } from "@/lib/hubPagination";
import {
  generateBreadcrumbSchema,
  generateItemListSchema,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";
import { ComparisonCardGrid } from "./ComparisonCardGrid";

interface ComparisonsHubProps {
  readonly locale: string;
  readonly page: number;
}

export async function ComparisonsHub({ locale, page }: ComparisonsHubProps) {
  setRequestLocale(locale);
  const [t, comparisons] = await Promise.all([
    getTranslations({ locale, namespace: "comparisons" }),
    getTranslatedComparisons(locale),
  ]);

  const webPageSchema = generateWebPageSchema(
    t("hub_title"),
    t("hub_subtitle"),
    `${siteConfig.url}/compare`,
    [
      { name: "Home", url: siteConfig.url },
      { name: t("breadcrumb"), url: `${siteConfig.url}/compare` },
    ],
  );

  const breadcrumbSchema = generateBreadcrumbSchema([
    { name: "Home", url: siteConfig.url },
    { name: t("breadcrumb"), url: `${siteConfig.url}/compare` },
  ]);

  const itemListSchema = generateItemListSchema(
    comparisons.map((c) => ({
      name: `${t("gaia_vs", { name: c.name })}`,
      url: `${siteConfig.url}/compare/${c.slug}`,
    })),
  );

  // Page through the hub's category order: each page is a contiguous chunk of
  // the list the hub has always shown instead of a slice scattered across categories.
  const categories = comparisonCategoryGroups(comparisons, t);
  const orderedComparisons = categories.flatMap((category) => category.items);

  // Only the current page's comparisons are serialized: the full list is paged
  // so neither the HTML nor the RSC flight payload carries every card.
  const totalPages = hubPageCount(orderedComparisons.length);
  const currentPage = Math.min(Math.max(page, 1), totalPages);
  const pageSlugs = new Set(
    hubPageSlice(orderedComparisons, currentPage).map((c) => c.slug),
  );
  const pageSections = categories.flatMap((category) => {
    const items = category.items.filter((comparison) =>
      pageSlugs.has(comparison.slug),
    );
    return items.length > 0 ? [{ category, items }] : [];
  });

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

        {pageSections.map(({ category, items }, sectionIndex) => (
          <div key={category.slug} id={category.slug} className="mb-14">
            <div className="mb-6 flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2 border-b border-zinc-700 pb-3">
              <h2 className="text-xl font-semibold text-zinc-300">
                {category.label}
              </h2>
              <SiteLink
                href={comparisonCategoryPath(category.slug)}
                className="text-sm text-zinc-400 underline underline-offset-2 hover:text-zinc-200"
              >
                {t("all_category_comparisons", {
                  count: category.items.length,
                  category: category.label,
                })}
              </SiteLink>
            </div>
            <ComparisonCardGrid
              comparisons={items}
              vsLabel={(name) => t("gaia_vs", { name })}
              headingLevel="h3"
              section={sectionIndex}
            />
          </div>
        ))}

        <HubPagination
          pathname="/compare"
          page={currentPage}
          totalPages={totalPages}
        />
      </div>

      <FinalSection />
    </>
  );
}
