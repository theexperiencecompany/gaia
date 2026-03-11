import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { getTranslations, setRequestLocale } from "next-intl/server";
import ComparisonTable from "@/components/seo/ComparisonTable";
import FAQAccordion from "@/components/seo/FAQAccordion";
import JsonLd from "@/components/seo/JsonLd";
import { getTranslatedAlternative } from "@/features/alternatives/data/getTranslatedAlternative";
import { COMPARISON_CATEGORIES } from "@/features/comparisons/data/categories";
import { getAllComparisonSlugs } from "@/features/comparisons/data/comparisonsData";
import {
  getTranslatedComparison,
  getTranslatedComparisons,
} from "@/features/comparisons/data/getTranslatedComparison";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import { getTranslatedPersona } from "@/features/personas/data/getTranslatedPersona";
import { getAlternates } from "@/i18n/getAlternates";
import {
  generateBreadcrumbSchema,
  generateFAQSchema,
  generatePageMetadata,
  generateProductSchema,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";

interface PageProps {
  readonly params: Promise<{
    readonly locale: string;
    readonly slug: string;
  }>;
}

export async function generateStaticParams() {
  return getAllComparisonSlugs().map((slug) => ({ slug }));
}

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const { slug } = await params;
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
    alternates: {
      ...metadata.alternates,
      languages: getAlternates(`/compare/${slug}`),
    },
  };
}

export default async function ComparisonPage({ params }: PageProps) {
  const { locale, slug } = await params;
  setRequestLocale(locale);
  const t = await getTranslations();
  const data = await getTranslatedComparison(slug);

  if (!data) {
    notFound();
  }

  const hasAlternativePage =
    (await getTranslatedAlternative(slug)) !== undefined;

  const currentCategory = COMPARISON_CATEGORIES[slug] ?? "Other";
  const relatedComparisons = (await getTranslatedComparisons())
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

  return (
    <>
      <JsonLd
        data={[webPageSchema, breadcrumbSchema, faqSchema, productSchema]}
      />

      <article className="mx-auto max-w-4xl px-6 pt-36 pb-24">
        {/* Breadcrumb */}
        <nav className="mb-8 text-sm text-zinc-500">
          <Link href="/" className="hover:text-zinc-300">
            {t("common.home")}
          </Link>
          <span className="mx-2">/</span>
          <Link href="/compare" className="hover:text-zinc-300">
            {t("comparisons.breadcrumb")}
          </Link>
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

        {/* FAQ */}
        <section className="mb-16">
          <h2 className="mb-6 text-3xl font-semibold text-white">
            {t("common.faq")}
          </h2>
          <FAQAccordion faqs={data.faqs} />
        </section>

        {/* Cross-link to alternative-to page */}
        {hasAlternativePage && (
          <section className="mb-16 border-t border-zinc-800 pt-8">
            <p className="text-sm text-zinc-500">
              {t("comparisons.looking_for_alternative", { name: data.name })}{" "}
              <Link
                href={`/alternative-to/${slug}`}
                className="text-zinc-400 underline underline-offset-2 hover:text-zinc-200"
              >
                {t("comparisons.see_complete_guide")} &rarr;{" "}
                {t("comparisons.best_alternative_year", { name: data.name })}
              </Link>
            </p>
          </section>
        )}

        {/* Related Comparisons */}
        {relatedComparisons.length > 0 && (
          <section className="mb-16">
            <h2 className="mb-6 text-3xl font-semibold text-white">
              {t("comparisons.compare_more_tools", {
                category: currentCategory,
              })}
            </h2>
            <div className="grid gap-4 sm:grid-cols-3">
              {relatedComparisons.map((comp) => (
                <Link
                  key={comp.slug}
                  href={`/compare/${comp.slug}`}
                  className="group rounded-2xl bg-zinc-800 p-5 transition-all hover:bg-zinc-700/50"
                >
                  <h3 className="mb-1 text-base font-medium text-white group-hover:text-primary">
                    {t("comparisons.gaia_vs", { name: comp.name })}
                  </h3>
                  <p className="text-xs text-zinc-400">{comp.tagline}</p>
                </Link>
              ))}
            </div>
          </section>
        )}

        {/* GAIA for Your Role */}
        {relatedPersonaData.length > 0 && (
          <section className="mb-16">
            <h2 className="mb-6 text-3xl font-semibold text-white">
              {t("comparisons.gaia_for_role")}
            </h2>
            <div className="grid gap-4 sm:grid-cols-3">
              {relatedPersonaData.map((persona) => (
                <Link
                  key={persona.slug}
                  href={`/for/${persona.slug}`}
                  className="group rounded-2xl bg-zinc-800 p-5 transition-all hover:bg-zinc-700/50"
                >
                  <h3 className="mb-2 text-base font-medium text-white group-hover:text-primary">
                    {t("comparisons.gaia_for_persona", { role: persona.role })}
                  </h3>
                  <p className="line-clamp-2 text-xs leading-relaxed text-zinc-400">
                    {persona.metaDescription}
                  </p>
                </Link>
              ))}
            </div>
          </section>
        )}

        {/* Explore More */}
        <section className="mb-16">
          <h2 className="mb-6 text-3xl font-semibold text-white">
            {t("common.explore_more")}
          </h2>
          <div className="grid gap-4 sm:grid-cols-2">
            <Link
              href="/learn"
              className="group rounded-2xl bg-zinc-800 p-5 transition-all hover:bg-zinc-700/50"
            >
              <h3 className="mb-2 text-lg font-medium text-white transition-colors group-hover:text-primary">
                {t("comparisons.ai_glossary")}
              </h3>
              <p className="text-sm leading-relaxed text-zinc-400">
                {t("comparisons.ai_glossary_desc", { name: data.name })}
              </p>
            </Link>
            <Link
              href="/for"
              className="group rounded-2xl bg-zinc-800 p-5 transition-all hover:bg-zinc-700/50"
            >
              <h3 className="mb-2 text-lg font-medium text-white transition-colors group-hover:text-primary">
                {t("comparisons.gaia_for_role")}
              </h3>
              <p className="text-sm leading-relaxed text-zinc-400">
                {t("comparisons.gaia_for_role_desc")}
              </p>
            </Link>
          </div>
        </section>
      </article>
      <FinalSection />
    </>
  );
}
