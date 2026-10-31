import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getTranslations, setRequestLocale } from "next-intl/server";
import { CategoryHubPage } from "@/components/seo/CategoryHubPage";
import { getAllTranslatedGlossaryTerms } from "@/features/glossary/data/getTranslatedGlossary";
import {
  glossaryCategoryGroups,
  glossaryCategoryPath,
} from "@/features/glossary/data/glossaryCategories";
import { getAllGlossaryTerms } from "@/features/glossary/data/glossaryData";
import { generateLocalizedPageMetadata } from "@/i18n/getAlternates";
import { prerenderedMarketingParams } from "@/lib/selfhost";
import { siteConfig } from "@/lib/seo";
import { GlossaryTermGrid } from "../../GlossaryTermGrid";

interface PageProps {
  readonly params: Promise<{
    readonly locale: string;
    readonly category: string;
  }>;
}

export function generateStaticParams() {
  // Labels do not decide which categories exist, so the message key stands in for them.
  return prerenderedMarketingParams(async () =>
    glossaryCategoryGroups(await getAllGlossaryTerms(), (key) => key).map(
      (category) => ({ category: category.slug }),
    ),
  );
}

export const dynamicParams = false;

async function findCategory(slug: string, locale: string) {
  const [t, terms] = await Promise.all([
    getTranslations({ locale, namespace: "glossary" }),
    getAllTranslatedGlossaryTerms(locale),
  ]);
  return glossaryCategoryGroups(terms, t).find(
    (category) => category.slug === slug,
  );
}

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const { locale, category: slug } = await params;
  const [t, category] = await Promise.all([
    getTranslations({ locale, namespace: "glossary" }),
    findCategory(slug, locale),
  ]);
  if (!category) return {};
  const values = { category: category.label, count: category.items.length };
  return generateLocalizedPageMetadata({
    title: t("category_meta_title", values),
    description: t("category_meta_description", values),
    path: glossaryCategoryPath(category.slug),
    keywords: [
      `${category.label} glossary`,
      `${category.label} terms`,
      "AI glossary",
    ],
    locale,
  });
}

export default async function GlossaryCategoryPage({ params }: PageProps) {
  const { locale, category: slug } = await params;
  setRequestLocale(locale);
  const [t, tCommon, category] = await Promise.all([
    getTranslations({ locale, namespace: "glossary" }),
    getTranslations({ locale, namespace: "common" }),
    findCategory(slug, locale),
  ]);
  if (!category) notFound();

  const pageUrl = `${siteConfig.url}${glossaryCategoryPath(category.slug)}`;
  const subtitle = t("category_page_subtitle", {
    category: category.label,
    count: category.items.length,
  });
  return (
    <CategoryHubPage
      title={category.label}
      breadcrumbLabel={category.label}
      subtitle={subtitle}
      pageUrl={pageUrl}
      homeLabel={tCommon("home")}
      hubLabel={t("breadcrumb")}
      hubHref="/learn"
      categoryLabel={category.label}
      items={category.items.map((term) => ({
        name: term.term,
        url: `${siteConfig.url}/learn/${term.slug}`,
      }))}
    >
      <GlossaryTermGrid terms={category.items} />
    </CategoryHubPage>
  );
}
