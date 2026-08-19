import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getTranslations, setRequestLocale } from "next-intl/server";
import JsonLd from "@/components/seo/JsonLd";
import { getAllAlternativeSlugs } from "@/features/alternatives/data/alternativesData";
import {
  getTranslatedAlternative,
  getTranslatedAlternatives,
} from "@/features/alternatives/data/getTranslatedAlternative";
import { COMPARISON_CATEGORIES } from "@/features/comparisons/data/categories";
import {
  getTranslatedComparison,
  getTranslatedComparisons,
} from "@/features/comparisons/data/getTranslatedComparison";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import { getLocalizedAlternates } from "@/i18n/getAlternates";
import {
  generateBreadcrumbSchema,
  generateFAQSchema,
  generateHowToSchema,
  generatePageMetadata,
  generateProductSchema,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";
import { AlternativeAdvantages } from "./components/AlternativeAdvantages";
import { AlternativeBreadcrumb } from "./components/AlternativeBreadcrumb";
import { AlternativeComparisonTable } from "./components/AlternativeComparisonTable";
import { AlternativeExploreMore } from "./components/AlternativeExploreMore";
import { AlternativeFaq } from "./components/AlternativeFaq";
import { AlternativeFitScore } from "./components/AlternativeFitScore";
import { AlternativeHero } from "./components/AlternativeHero";
import { AlternativeMigration } from "./components/AlternativeMigration";
import { AlternativePainPoints } from "./components/AlternativePainPoints";
import { AlternativeRelated } from "./components/AlternativeRelated";
import { AlternativeReplaces } from "./components/AlternativeReplaces";

interface PageProps {
  readonly params: Promise<{
    readonly locale: string;
    readonly slug: string;
  }>;
}

export async function generateStaticParams() {
  const slugs = await getAllAlternativeSlugs();
  return slugs.map((slug) => ({ slug }));
}

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const { locale, slug } = await params;
  const data = await getTranslatedAlternative(slug);
  if (!data) return { title: "Alternative Not Found" };
  const metadata = generatePageMetadata({
    title: data.metaTitle,
    description: data.metaDescription,
    path: `/alternative-to/${slug}`,
    keywords: data.keywords,
  });
  return {
    ...metadata,
    alternates: getLocalizedAlternates(`/alternative-to/${slug}`, locale),
  };
}

export default async function AlternativePage({ params }: PageProps) {
  const { locale, slug } = await params;
  setRequestLocale(locale);
  const [t, data, comparisonData, allComparisons, allAlternatives] =
    await Promise.all([
      getTranslations(),
      getTranslatedAlternative(slug),
      getTranslatedComparison(slug),
      getTranslatedComparisons(),
      getTranslatedAlternatives(),
    ]);

  if (!data) notFound();

  const hasComparisonPage = comparisonData !== undefined;
  const currentCategory = COMPARISON_CATEGORIES[slug] ?? "Other";
  const relatedComparisons = allComparisons
    .filter(
      (c) =>
        c.slug !== slug && COMPARISON_CATEGORIES[c.slug] === currentCategory,
    )
    .slice(0, 3);
  const relatedAlternatives = allAlternatives
    .filter((a) => a.slug !== slug && a.category === data.category)
    .slice(0, 3);

  const webPageSchema = generateWebPageSchema(
    data.metaTitle,
    data.metaDescription,
    `${siteConfig.url}/alternative-to/${slug}`,
    [
      { name: "Home", url: siteConfig.url },
      { name: "Alternatives", url: `${siteConfig.url}/alternative-to` },
      {
        name: `Best ${data.name} Alternative`,
        url: `${siteConfig.url}/alternative-to/${slug}`,
      },
    ],
  );
  const breadcrumbSchema = generateBreadcrumbSchema([
    { name: "Home", url: siteConfig.url },
    { name: "Alternatives", url: `${siteConfig.url}/alternative-to` },
    {
      name: `Best ${data.name} Alternative`,
      url: `${siteConfig.url}/alternative-to/${slug}`,
    },
  ]);
  const faqSchema = generateFAQSchema(data.faqs);
  const howToSchema = generateHowToSchema(
    `How to migrate from ${data.name} to GAIA`,
    `Step-by-step guide to switching from ${data.name} to GAIA.`,
    data.migrationSteps.map((step) => ({ name: step, text: step })),
  );

  return (
    <>
      <JsonLd
        data={[
          webPageSchema,
          breadcrumbSchema,
          faqSchema,
          howToSchema,
          generateProductSchema(),
        ]}
      />

      <article className="mx-auto max-w-4xl px-6 pt-36 pb-24">
        <AlternativeBreadcrumb t={t} name={data.name} />
        <AlternativeHero
          t={t}
          name={data.name}
          tagline={data.tagline}
          whyPeopleLook={data.whyPeopleLook}
        />
        <AlternativePainPoints
          t={t}
          name={data.name}
          painPoints={data.painPoints}
        />
        <AlternativeFitScore t={t} name={data.name} score={data.gaiaFitScore} />
        <AlternativeReplaces
          t={t}
          name={data.name}
          replaces={data.gaiaReplaces}
        />
        <AlternativeComparisonTable t={t} data={data} />
        <AlternativeAdvantages t={t} advantages={data.gaiaAdvantages} />
        <AlternativeMigration
          t={t}
          name={data.name}
          steps={data.migrationSteps}
        />
        <AlternativeFaq t={t} faqs={data.faqs} />
        <AlternativeRelated
          t={t}
          relatedAlternatives={relatedAlternatives}
          relatedComparisons={relatedComparisons}
          slug={slug}
          dataName={data.name}
          hasComparisonPage={hasComparisonPage}
        />
        <AlternativeExploreMore t={t} />
      </article>

      <FinalSection />
    </>
  );
}
