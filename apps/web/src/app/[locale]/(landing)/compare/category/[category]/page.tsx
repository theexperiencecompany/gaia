import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getTranslations, setRequestLocale } from "next-intl/server";
import JsonLd from "@/components/seo/JsonLd";
import { PageBreadcrumbs } from "@/components/seo/PageBreadcrumbs";
import {
  comparisonCategoryGroups,
  comparisonCategoryPath,
} from "@/features/comparisons/data/comparisonCategories";
import { getAllComparisons } from "@/features/comparisons/data/comparisonsData";
import { getTranslatedComparisons } from "@/features/comparisons/data/getTranslatedComparison";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import { generateLocalizedPageMetadata } from "@/i18n/getAlternates";
import { prerenderedMarketingParams } from "@/lib/selfhost";
import {
  generateBreadcrumbSchema,
  generateItemListSchema,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";
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
  const breadcrumbs = [
    { name: "Home", url: siteConfig.url },
    { name: t("breadcrumb"), url: `${siteConfig.url}/compare` },
    { name: title, url: pageUrl },
  ];

  return (
    <>
      <JsonLd
        data={[
          generateWebPageSchema(title, subtitle, pageUrl, breadcrumbs),
          generateBreadcrumbSchema(breadcrumbs),
          generateItemListSchema(
            category.items.map((comparison) => ({
              name: t("gaia_vs", { name: comparison.name }),
              url: `${siteConfig.url}/compare/${comparison.slug}`,
            })),
          ),
        ]}
      />

      <div className="mx-auto max-w-5xl px-6 pt-36 pb-24">
        <PageBreadcrumbs
          className="mb-8"
          items={[
            { label: tCommon("home"), href: "/" },
            { label: t("breadcrumb"), href: "/compare" },
            { label: category.label },
          ]}
        />
        <header className="mb-16">
          <h1 className="mb-4 font-serif text-5xl font-normal text-white md:text-6xl">
            {title}
          </h1>
          <p className="max-w-2xl text-xl text-zinc-400">{subtitle}</p>
        </header>

        <ComparisonCardGrid
          comparisons={category.items}
          vsLabel={(name) => t("gaia_vs", { name })}
        />
      </div>

      <FinalSection />
    </>
  );
}
