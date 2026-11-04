import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getTranslations, setRequestLocale } from "next-intl/server";
import { CategoryHubPage } from "@/components/seo/CategoryHubPage";
import {
  comparisonCategoryGroups,
  comparisonCategoryPath,
} from "@/features/comparisons/data/comparisonCategories";
import { getAllComparisons } from "@/features/comparisons/data/comparisonsData";
import { getTranslatedComparisons } from "@/features/comparisons/data/getTranslatedComparison";
import { generateLocalizedPageMetadata } from "@/i18n/getAlternates";
import { prerenderedMarketingParams } from "@/lib/selfhost";
import { siteConfig } from "@/lib/seo";
import { ComparisonCardGrid } from "../../ComparisonCardGrid";

interface PageProps {
  readonly params: Promise<{
    readonly locale: string;
    readonly category: string;
  }>;
}

export function generateStaticParams() {
  return prerenderedMarketingParams(async () =>
    comparisonCategoryGroups(await getAllComparisons()).map((category) => ({
      category: category.slug,
    })),
  );
}

export const dynamicParams = false;

async function findCategory(slug: string, locale?: string) {
  const categories = comparisonCategoryGroups(
    await getTranslatedComparisons(locale),
  );
  return categories.find((category) => category.slug === slug);
}

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const { locale, category: slug } = await params;
  const [t, category] = await Promise.all([
    getTranslations({ locale, namespace: "comparisons" }),
    findCategory(slug, locale),
  ]);
  if (!category) return {};
  const values = { category: category.label, count: category.items.length };
  return generateLocalizedPageMetadata({
    title: t("category_meta_title", values),
    description: t("category_meta_description", values),
    path: comparisonCategoryPath(category.slug),
    keywords: [
      `${category.label} comparison`,
      `best ${category.label} tools`,
      "GAIA comparisons",
    ],
    locale,
  });
}

export default async function ComparisonCategoryPage({ params }: PageProps) {
  const { locale, category: slug } = await params;
  setRequestLocale(locale);
  const [t, tCommon, category] = await Promise.all([
    getTranslations({ locale, namespace: "comparisons" }),
    getTranslations({ locale, namespace: "common" }),
    findCategory(slug, locale),
  ]);
  if (!category) notFound();

  const pageUrl = `${siteConfig.url}${comparisonCategoryPath(category.slug)}`;
  const title = t("category_page_title", { category: category.label });
  const subtitle = t("category_page_subtitle", {
    category: category.label,
    count: category.items.length,
  });
  return (
    <CategoryHubPage
      title={title}
      breadcrumbLabel={title}
      subtitle={subtitle}
      pageUrl={pageUrl}
      homeLabel={tCommon("home")}
      hubLabel={t("breadcrumb")}
      hubHref="/compare"
      categoryLabel={category.label}
      items={category.items.map((comparison) => ({
        name: t("gaia_vs", { name: comparison.name }),
        url: `${siteConfig.url}/compare/${comparison.slug}`,
      }))}
    >
      <ComparisonCardGrid
        comparisons={category.items}
        vsLabel={(name) => t("gaia_vs", { name })}
      />
    </CategoryHubPage>
  );
}
