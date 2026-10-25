import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getTranslations, setRequestLocale } from "next-intl/server";
import ComparisonTable from "@/components/seo/ComparisonTable";
import DocsGuidesSection from "@/components/seo/DocsGuidesSection";
import FAQAccordion from "@/components/seo/FAQAccordion";
import JsonLd from "@/components/seo/JsonLd";
import { SiteLink } from "@/components/seo/SiteLink";
import { getTranslatedAlternative } from "@/features/alternatives/data/getTranslatedAlternative";
import { COMPARISON_CATEGORIES } from "@/features/comparisons/data/categories";
import { getAllComparisonSlugs } from "@/features/comparisons/data/comparisonsData";
import {
  getTranslatedComparison,
  getTranslatedComparisons,
} from "@/features/comparisons/data/getTranslatedComparison";
import { getMarketplacePath } from "@/features/integrations/lib/serverMarketplaceApi";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import { getTranslatedPersona } from "@/features/personas/data/getTranslatedPersona";
import { getLocalizedAlternates } from "@/i18n/getAlternates";
import { isRedirectedPath } from "@/lib/canonicalLinks";
import { COMPARE_DOCS_LINKS } from "@/lib/docs-links";
import { prerenderedMarketingParams } from "@/lib/selfhost";
import {
  generateBreadcrumbSchema,
  generateFAQSchema,
  generatePageMetadata,
  generateProductSchema,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";
import {
  CompareExploreMore,
  CompareRelatedSections,
} from "./CompareLinkSections";

interface PageProps {
  readonly params: Promise<{
    readonly locale: string;
    readonly slug: string;
  }>;
}

async function allStaticParams() {
  const slugs = await getAllComparisonSlugs();
  return slugs.map((slug) => ({ slug }));
}

export function generateStaticParams() {
  return prerenderedMarketingParams(allStaticParams);
}

export const dynamicParams = false;

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const { locale, slug } = await params;
  const data = await getTranslatedComparison(slug);

  if (!data) {
    return { title: "Comparison Not Found" };
  }

  const metadata = generatePageMetadata({
    title: data.metaTitle,
    description: data.metaDescription,
    path: `/compare/${slug}`,
    keywords: data.keywords,
  });

  return {
    ...metadata,
    alternates: getLocalizedAlternates(`/compare/${slug}`, locale),
  };
}

export default async function ComparisonPage({ params }: PageProps) {
  const { locale, slug } = await params;
  setRequestLocale(locale);
  const [t, data, alternativeData, allComparisons] = await Promise.all([
    getTranslations(),
    getTranslatedComparison(slug),
    getTranslatedAlternative(slug),
    getTranslatedComparisons(),
  ]);

  if (!data) {
    notFound();
  }

  const hasAlternativePage =
    alternativeData !== undefined &&
    !isRedirectedPath(`/alternative-to/${slug}`);

  const currentCategory = COMPARISON_CATEGORIES[slug] ?? "Other";
  const relatedComparisons = allComparisons
    .filter(
      (c) =>
        c.slug !== slug && COMPARISON_CATEGORIES[c.slug] === currentCategory,
    )
    .slice(0, 3);

  const relatedPersonaData = (
    await Promise.all(
      (data.relatedPersonas ?? []).map((personaSlug) =>
        getTranslatedPersona(personaSlug),
      ),
    )
  ).filter((p): p is NonNullable<typeof p> => p !== undefined);

  const docsGuides = COMPARE_DOCS_LINKS[slug] ?? [];

  const webPageSchema = generateWebPageSchema(
    data.metaTitle,
    data.metaDescription,
    `${siteConfig.url}/compare/${slug}`,
    [
      { name: "Home", url: siteConfig.url },
      { name: "Comparisons", url: `${siteConfig.url}/compare` },
      {
        name: `GAIA vs ${data.name}`,
        url: `${siteConfig.url}/compare/${slug}`,
      },
    ],
  );

  const breadcrumbSchema = generateBreadcrumbSchema([
    { name: "Home", url: siteConfig.url },
    { name: "Comparisons", url: `${siteConfig.url}/compare` },
    {
      name: `GAIA vs ${data.name}`,
      url: `${siteConfig.url}/compare/${slug}`,
    },
  ]);

  const faqSchema = generateFAQSchema(data.faqs);
  const productSchema = generateProductSchema();

  // "Connect {name}" CTA only where the marketplace slug verifiably exists.
  const marketplacePath = await getMarketplacePath(slug);

  return (
    <>
      <JsonLd
        data={[webPageSchema, breadcrumbSchema, faqSchema, productSchema]}
      />

      <article className="mx-auto max-w-4xl px-6 pt-36 pb-24">
        {/* Breadcrumb */}
        <nav className="mb-8 text-sm text-zinc-500">
          <SiteLink href="/" className="hover:text-zinc-300">
            {t("common.home")}
          </SiteLink>
          <span className="mx-2">/</span>
          <SiteLink href="/compare" className="hover:text-zinc-300">
            {t("comparisons.breadcrumb")}
          </SiteLink>
          <span className="mx-2">/</span>
          <span className="text-zinc-300">
            {t("comparisons.gaia_vs", { name: data.name })}
          </span>
        </nav>

        {/* Hero */}
        <header className="mb-16">
          <h1 className="mb-4 font-serif text-5xl font-normal text-white md:text-6xl">
            {t("comparisons.gaia_vs", { name: data.name })}
          </h1>
          <p className="text-xl leading-relaxed text-zinc-400">
            {data.description}
          </p>
        </header>

        {/* Introduction */}
        <section className="mb-16">
          <p className="text-lg leading-relaxed text-zinc-300">{data.intro}</p>
        </section>

        {/* Comparison Table */}
        <section className="mb-16">
          <h2 className="mb-6 text-3xl font-semibold text-white">
            {t("comparisons.feature_comparison")}
          </h2>
          <ComparisonTable
            ariaLabel={`GAIA vs ${data.name} feature comparison`}
            columns={[
              {
                key: "feature",
                label: t("comparisons.feature_column"),
                headerClassName: "text-zinc-500",
                cellClassName: "font-medium text-zinc-300",
              },
              {
                key: "gaia",
                label: t("comparisons.gaia_column"),
                headerClassName: "text-primary",
                cellClassName: "text-emerald-400",
              },
              {
                key: "competitor",
                label: data.name,
                headerClassName: "text-zinc-400",
                cellClassName: "text-zinc-400",
              },
            ]}
            rows={data.rows}
          />
        </section>

        {/* Advantages */}
        <div className="mb-16 grid gap-8 md:grid-cols-2">
          <section>
            <h2 className="mb-4 text-2xl font-semibold text-emerald-400">
              {t("comparisons.why_choose_gaia")}
            </h2>
            <ul className="space-y-3">
              {data.gaiaAdvantages.map((advantage) => (
                <li
                  key={advantage}
                  className="flex items-start gap-3 text-zinc-300"
                >
                  <span className="mt-1 text-emerald-400">+</span>
                  <span>{advantage}</span>
                </li>
              ))}
            </ul>
          </section>
          <section>
            <h2 className="mb-4 text-2xl font-semibold text-zinc-400">
              {t("comparisons.where_excels", { name: data.name })}
            </h2>
            <ul className="space-y-3">
              {data.competitorAdvantages.map((advantage) => (
                <li
                  key={advantage}
                  className="flex items-start gap-3 text-zinc-400"
                >
                  <span className="mt-1">+</span>
                  <span>{advantage}</span>
                </li>
              ))}
            </ul>
          </section>
        </div>

        {/* Verdict */}
        <section className="mb-16 rounded-3xl bg-zinc-800 p-8">
          <h2 className="mb-4 text-2xl font-semibold text-white">
            {t("comparisons.the_verdict")}
          </h2>
          <p className="text-lg leading-relaxed text-zinc-300">
            {data.verdict}
          </p>
        </section>

        {/* Connect CTA: only rendered when the marketplace page exists */}
        {marketplacePath && (
          <section className="mb-16 rounded-3xl bg-zinc-800 p-8">
            <h2 className="mb-3 text-2xl font-semibold text-white">
              Connect {data.name} to GAIA
            </h2>
            <p className="mb-6 leading-relaxed text-zinc-400">
              Use {data.name} with your AI assistant: connect it in under two
              minutes, then automate {data.name} workflows in plain English.
            </p>
            <SiteLink
              href={marketplacePath}
              className="inline-flex items-center rounded-full bg-primary px-6 py-3 text-sm font-medium text-black transition-opacity hover:opacity-90"
            >
              Connect {data.name}
            </SiteLink>
          </section>
        )}

        {/* FAQ */}
        <section className="mb-16">
          <h2 className="mb-6 text-3xl font-semibold text-white">
            {t("common.faq")}
          </h2>
          <FAQAccordion faqs={data.faqs} />
        </section>

        <CompareRelatedSections
          name={data.name}
          alternativeHref={
            hasAlternativePage ? `/alternative-to/${slug}` : null
          }
          category={currentCategory}
          relatedComparisons={relatedComparisons}
          relatedPersonas={relatedPersonaData}
          t={t}
        />

        <DocsGuidesSection
          heading={t("common.docs_guides")}
          guides={docsGuides}
        />

        <CompareExploreMore name={data.name} t={t} />
      </article>
      <FinalSection />
    </>
  );
}
