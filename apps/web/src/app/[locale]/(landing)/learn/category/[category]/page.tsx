import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getTranslations, setRequestLocale } from "next-intl/server";
import JsonLd from "@/components/seo/JsonLd";
import { PageBreadcrumbs } from "@/components/seo/PageBreadcrumbs";
import { getAllTranslatedGlossaryTerms } from "@/features/glossary/data/getTranslatedGlossary";
import {
  glossaryCategoryGroups,
  glossaryCategoryPath,
} from "@/features/glossary/data/glossaryCategories";
import { getAllGlossaryTerms } from "@/features/glossary/data/glossaryData";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import { generateLocalizedPageMetadata } from "@/i18n/getAlternates";
import { prerenderedMarketingParams } from "@/lib/selfhost";
import {
  generateBreadcrumbSchema,
  generateItemListSchema,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";
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
  const breadcrumbs = [
    { name: "Home", url: siteConfig.url },
    { name: t("breadcrumb"), url: `${siteConfig.url}/learn` },
    { name: category.label, url: pageUrl },
  ];

  return (
    <>
      <JsonLd
        data={[
          generateWebPageSchema(category.label, subtitle, pageUrl, breadcrumbs),
          generateBreadcrumbSchema(breadcrumbs),
          generateItemListSchema(
            category.items.map((term) => ({
              name: term.term,
              url: `${siteConfig.url}/learn/${term.slug}`,
            })),
          ),
        ]}
      />

      <div className="mx-auto max-w-5xl px-6 pt-36 pb-24">
        <PageBreadcrumbs
          className="mb-8"
          items={[
            { label: tCommon("home"), href: "/" },
            { label: t("breadcrumb"), href: "/learn" },
            { label: category.label },
          ]}
        />
        <header className="mb-16">
          <h1 className="mb-4 font-serif text-5xl font-normal text-white md:text-6xl">
            {category.label}
          </h1>
          <p className="max-w-2xl text-xl text-zinc-400">{subtitle}</p>
        </header>

        <GlossaryTermGrid terms={category.items} />
      </div>

      <FinalSection />
    </>
  );
}
