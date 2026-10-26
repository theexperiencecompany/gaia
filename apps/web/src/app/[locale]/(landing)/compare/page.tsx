import type { Metadata } from "next";
import { getTranslations, setRequestLocale } from "next-intl/server";
import { HubGroupSection } from "@/components/seo/HubGroupSection";
import { HubIndex } from "@/components/seo/HubPageNav";
import JsonLd from "@/components/seo/JsonLd";
import {
  comparisonCategoryGroups,
  comparisonCategoryPath,
} from "@/features/comparisons/data/comparisonCategories";
import { getTranslatedComparisons } from "@/features/comparisons/data/getTranslatedComparison";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import { generateLocalizedPageMetadata } from "@/i18n/getAlternates";
import {
  generateBreadcrumbSchema,
  generateItemListSchema,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";
import { ComparisonCardGrid } from "./ComparisonCardGrid";

/** Comparisons each category's section previews: two rows of three, the rest one click away on its category page. */
const COMPARISONS_PER_CATEGORY = 6;

interface PageProps {
  readonly params: Promise<{
    readonly locale: string;
  }>;
}

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const { locale } = await params;
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

export default async function ComparisonsHubPage({ params }: PageProps) {
  const { locale } = await params;
  setRequestLocale(locale);
  const [t, tCommon, comparisons] = await Promise.all([
    getTranslations({ locale, namespace: "comparisons" }),
    getTranslations({ locale, namespace: "common" }),
    getTranslatedComparisons(locale),
  ]);
  const categories = comparisonCategoryGroups(comparisons);

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
    categories.map((category) => ({
      name: t("category_page_title", { category: category.label }),
      url: `${siteConfig.url}${comparisonCategoryPath(category.slug)}`,
    })),
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

        <HubIndex
          label={tCommon("section_nav_label")}
          entries={categories.map((category) => ({
            id: `category-${category.slug}`,
            label: category.label,
            count: category.items.length,
          }))}
        />

        {categories.map((category) => (
          <HubGroupSection
            key={category.slug}
            id={`category-${category.slug}`}
            heading={category.label}
            headingClassName="text-2xl font-semibold text-white"
            allLink={{
              href: comparisonCategoryPath(category.slug),
              label: t("all_category_comparisons", {
                count: category.items.length,
                category: category.label,
              }),
            }}
          >
            <ComparisonCardGrid
              comparisons={category.items.slice(0, COMPARISONS_PER_CATEGORY)}
              vsLabel={(name) => t("gaia_vs", { name })}
            />
          </HubGroupSection>
        ))}
      </div>

      <FinalSection />
    </>
  );
}
