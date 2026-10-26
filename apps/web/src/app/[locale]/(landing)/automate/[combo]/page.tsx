import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getTranslations, setRequestLocale } from "next-intl/server";
import DocsGuidesSection from "@/components/seo/DocsGuidesSection";
import FAQAccordion from "@/components/seo/FAQAccordion";
import JsonLd from "@/components/seo/JsonLd";
import { RelatedAutomationsGrid } from "@/components/seo/RelatedAutomationsGrid";
import { getAllAlternativeSlugs } from "@/features/alternatives/data/alternativesData";
import { getAllComparisonSlugs } from "@/features/comparisons/data/comparisonsData";
import { getAllComboSlugs } from "@/features/integrations/data/combosData";
import {
  getTranslatedCombo,
  getTranslatedCombos,
} from "@/features/integrations/data/getTranslatedCombo";
import { relatedCombos } from "@/features/integrations/lib/relatedCombos";
import { getMarketplacePath } from "@/features/integrations/lib/serverMarketplaceApi";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import { generateLocalizedPageMetadata } from "@/i18n/getAlternates";
import { getAutomateDocsLinks } from "@/lib/docs-links";
import { prerenderedMarketingParams } from "@/lib/selfhost";
import {
  generateBreadcrumbSchema,
  generateFAQSchema,
  generateHowToSchema,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";
import { ComboIntro, ComboUseCases } from "./ComboContent";
import { ComboHowItWorks } from "./ComboHowItWorks";
import { ComboCompareLinks, ComboIntegrationLinks } from "./ComboLinkSections";
import { ComboMoreLink } from "./ComboRelatedLinks";
import { ComboBreadcrumb, ComboHero } from "./ComboSections";

interface PageProps {
  readonly params: Promise<{
    readonly locale: string;
    readonly combo: string;
  }>;
}

async function allStaticParams() {
  const slugs = await getAllComboSlugs();
  return slugs.map((slug) => ({ combo: slug }));
}

export function generateStaticParams() {
  return prerenderedMarketingParams(allStaticParams);
}

export const dynamicParams = false;

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const { locale, combo } = await params;
  const data = await getTranslatedCombo(combo);

  if (!data) {
    return { title: "Integration Not Found" };
  }

  return generateLocalizedPageMetadata({
    title: data.metaTitle,
    description: data.metaDescription,
    path: `/automate/${combo}`,
    keywords: data.keywords,
    locale,
  });
}

export default async function AutomateComboPage({ params }: PageProps) {
  const { locale, combo } = await params;
  setRequestLocale(locale);
  const [t, data, allCombos, comparisonSlugs, alternativeSlugs] =
    await Promise.all([
      getTranslations(),
      getTranslatedCombo(combo),
      getTranslatedCombos(),
      getAllComparisonSlugs(),
      getAllAlternativeSlugs(),
    ]);

  if (!data) {
    notFound();
  }
  // getTranslatedCombos is _slugs-driven (victims excluded), so every entry
  // here links a live page.
  const moreCombos = relatedCombos(data, allCombos);

  const docsGuides = getAutomateDocsLinks(data.toolASlug, data.toolBSlug);

  const pageUrl = `${siteConfig.url}/automate/${combo}`;

  const breadcrumbItems = [
    { name: "Home", url: siteConfig.url },
    { name: "Marketplace", url: `${siteConfig.url}/marketplace` },
    {
      name: `${data.toolA} + ${data.toolB}`,
      url: pageUrl,
    },
  ];

  const breadcrumbSchema = generateBreadcrumbSchema(breadcrumbItems);

  const webPageSchema = generateWebPageSchema(
    data.metaTitle,
    data.metaDescription,
    pageUrl,
    breadcrumbItems,
  );

  const howToSchema = generateHowToSchema(
    `How to automate ${data.toolA} + ${data.toolB} with GAIA`,
    `Set up automated workflows between ${data.toolA} and ${data.toolB} using GAIA in three steps.`,
    data.howItWorks.map((h) => ({ name: h.step, text: h.description })),
  );

  const faqSchema = generateFAQSchema(data.faqs);

  // Direct detail links where the marketplace slug verifiably exists;
  // otherwise the search page stays the fallback (never link a 404).
  const [toolAPath, toolBPath] = await Promise.all([
    getMarketplacePath(data.toolASlug),
    getMarketplacePath(data.toolBSlug),
  ]);
  const toolAHref =
    toolAPath ?? `/marketplace?search=${encodeURIComponent(data.toolA)}`;
  const toolBHref =
    toolBPath ?? `/marketplace?search=${encodeURIComponent(data.toolB)}`;

  // Head-to-head and alternative guides keyed by the same tool slugs the
  // combo datasets use; only link pages that verifiably exist (never a 404).
  const compareHrefFor = (toolSlug: string): string | null => {
    if (comparisonSlugs.includes(toolSlug)) return `/compare/${toolSlug}`;
    if (alternativeSlugs.includes(toolSlug)) {
      return `/alternative-to/${toolSlug}`;
    }
    return null;
  };
  const toolACompareHref = compareHrefFor(data.toolASlug);
  const toolBCompareHref = compareHrefFor(data.toolBSlug);

  return (
    <>
      <JsonLd
        data={[webPageSchema, breadcrumbSchema, howToSchema, faqSchema]}
      />

      <article className="mx-auto max-w-4xl px-6 pt-36 pb-24">
        <ComboBreadcrumb data={data} t={t} />
        <ComboHero data={data} t={t} />
        <ComboIntro data={data} />
        <ComboUseCases data={data} t={t} />
        <ComboHowItWorks data={data} t={t} />
        <section className="mb-16">
          <h2 className="mb-6 text-3xl font-semibold text-white">
            {t("common.faq")}
          </h2>
          <FAQAccordion faqs={data.faqs} />
        </section>
        <ComboIntegrationLinks
          data={data}
          toolAHref={toolAHref}
          toolBHref={toolBHref}
          t={t}
        />
        <ComboCompareLinks
          data={data}
          toolACompareHref={toolACompareHref}
          toolBCompareHref={toolBCompareHref}
        />
        <RelatedAutomationsGrid
          heading={t("automate.more_automations_with", {
            toolA: data.toolA,
            toolB: data.toolB,
          })}
          combos={moreCombos}
          headingClassName="mb-6 text-2xl font-semibold text-white"
        />
        <DocsGuidesSection
          heading={t("common.docs_guides")}
          guides={docsGuides}
          headingClassName="mb-6 text-2xl font-semibold text-white"
        />
        <ComboMoreLink t={t} />
      </article>

      <FinalSection />
    </>
  );
}
