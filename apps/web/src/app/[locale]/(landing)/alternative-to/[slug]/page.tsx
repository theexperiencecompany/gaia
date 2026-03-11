import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { getTranslations, setRequestLocale } from "next-intl/server";
import ComparisonTable from "@/components/seo/ComparisonTable";
import FAQAccordion from "@/components/seo/FAQAccordion";
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
import { getAlternates } from "@/i18n/getAlternates";
import {
  generateBreadcrumbSchema,
  generateFAQSchema,
  generateHowToSchema,
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
  return getAllAlternativeSlugs().map((slug) => ({ slug }));
}

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const { slug } = await params;
  const data = await getTranslatedAlternative(slug);

  if (!data) {
    return { title: "Alternative Not Found" };
  }

  const metadata = generatePageMetadata({
    title: data.metaTitle,
    description: data.metaDescription,
    path: `/alternative-to/${slug}`,
    keywords: data.keywords,
  });
  return {
    ...metadata,
    alternates: {
      ...metadata.alternates,
      languages: getAlternates(`/alternative-to/${slug}`),
    },
  };
}

function FitScorePip({ filled }: { readonly filled: boolean }) {
  return (
    <span
      className={`inline-block h-3 w-3 rounded-full ${filled ? "bg-emerald-400" : "bg-zinc-700"}`}
    />
  );
}

function FitScoreRow({ score }: { readonly score: number }) {
  return (
    <div className="flex items-center gap-1.5">
      {[0, 1, 2, 3, 4].map((i) => (
        <FitScorePip key={`pip-${i}`} filled={i < score} />
      ))}
      <span className="ml-1 text-sm text-zinc-400">{score}/5</span>
    </div>
  );
}

export default async function AlternativePage({ params }: PageProps) {
  const { locale, slug } = await params;
  setRequestLocale(locale);
  const t = await getTranslations();
  const data = await getTranslatedAlternative(slug);

  if (!data) {
    notFound();
  }

  const hasComparisonPage = (await getTranslatedComparison(slug)) !== undefined;

  const currentCategory = COMPARISON_CATEGORIES[slug] ?? "Other";
  const relatedComparisons = (await getTranslatedComparisons())
    .filter(
      (c) =>
        c.slug !== slug && COMPARISON_CATEGORIES[c.slug] === currentCategory,
    )
    .slice(0, 3);

  const relatedAlternatives = (await getTranslatedAlternatives())
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
        {/* Breadcrumb */}
        <nav className="mb-8 text-sm text-zinc-500">
          <Link href="/" className="hover:text-zinc-300">
            {t("common.home")}
          </Link>
          <span className="mx-2">/</span>
          <Link href="/alternative-to" className="hover:text-zinc-300">
            {t("alternatives.breadcrumb")}
          </Link>
          <span className="mx-2">/</span>
          <span className="text-zinc-300">
            {t("alternatives.best_alternative", { name: data.name })}
          </span>
        </nav>

        {/* Hero */}
        <header className="mb-16">
          <h1 className="mb-4 font-serif text-5xl font-normal text-white md:text-6xl">
            {t("alternatives.best_alternative_year", { name: data.name })}
          </h1>
          <p className="text-xl leading-relaxed text-zinc-400">
            {data.tagline}
          </p>
        </header>

        {/* Why people look */}
        <section className="mb-16">
          <p className="text-lg leading-relaxed text-zinc-300">
            {data.whyPeopleLook}
          </p>
        </section>

        {/* Pain points */}
        <section className="mb-16">
          <h2 className="mb-6 text-3xl font-semibold text-white">
            {t("alternatives.why_people_look", { name: data.name })}
          </h2>
          <ul className="space-y-4">
            {data.painPoints.map((point) => (
              <li
                key={point}
                className="flex items-start gap-3 rounded-2xl bg-zinc-800 p-4 text-zinc-300"
              >
                <span className="mt-0.5 text-red-400 shrink-0">&#x2212;</span>
                <span>{point}</span>
              </li>
            ))}
          </ul>
        </section>

        {/* GAIA fit score */}
        <section className="mb-16 rounded-3xl bg-zinc-800 p-8">
          <h2 className="mb-2 text-2xl font-semibold text-white">
            {t("alternatives.how_well_replace", { name: data.name })}
          </h2>
          <p className="mb-4 text-sm text-zinc-500">
            {t("alternatives.honest_fit_score")}
          </p>
          <FitScoreRow score={data.gaiaFitScore} />
        </section>

        {/* What GAIA replaces */}
        <section className="mb-16">
          <h2 className="mb-6 text-3xl font-semibold text-white">
            {t("alternatives.what_gaia_replaces", { name: data.name })}
          </h2>
          <ul className="space-y-3">
            {data.gaiaReplaces.map((item) => (
              <li key={item} className="flex items-start gap-3 text-zinc-300">
                <span className="mt-1 text-emerald-400 shrink-0">&#x2714;</span>
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </section>

        {/* Comparison table */}
        {data.comparisonRows && data.comparisonRows.length > 0 && (
          <section className="mb-16">
            <h2 className="mb-6 text-3xl font-semibold text-white">
              {t("alternatives.feature_comparison", { name: data.name })}
            </h2>
            <ComparisonTable
              ariaLabel={`GAIA vs ${data.name} feature comparison`}
              columns={[
                {
                  key: "feature",
                  label: t("alternatives.feature_column"),
                  headerClassName: "text-zinc-500",
                  cellClassName: "font-medium text-zinc-300",
                },
                {
                  key: "gaia",
                  label: t("alternatives.gaia_column"),
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
              rows={data.comparisonRows}
            />
          </section>
        )}

        {/* GAIA advantages */}
        <section className="mb-16">
          <h2 className="mb-6 text-3xl font-semibold text-white">
            {t("alternatives.where_gaia_further")}
          </h2>
          <ul className="space-y-3">
            {data.gaiaAdvantages.map((advantage) => (
              <li
                key={advantage}
                className="flex items-start gap-3 text-zinc-300"
              >
                <span className="mt-1 text-emerald-400 shrink-0">+</span>
                <span>{advantage}</span>
              </li>
            ))}
          </ul>
        </section>

        {/* Migration steps */}
        <section className="mb-16">
          <h2 className="mb-6 text-3xl font-semibold text-white">
            {t("alternatives.how_to_migrate", { name: data.name })}
          </h2>
          <ol className="space-y-4">
            {data.migrationSteps.map((step, index) => (
              <li
                key={step}
                className="flex items-start gap-4 rounded-2xl bg-zinc-800 p-5"
              >
                <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-emerald-400/10 text-sm font-semibold text-emerald-400">
                  {index + 1}
                </span>
                <span className="mt-1 text-zinc-300">{step}</span>
              </li>
            ))}
          </ol>
        </section>

        {/* FAQ */}
        <section className="mb-16">
          <h2 className="mb-6 text-3xl font-semibold text-white">
            {t("common.faq")}
          </h2>
          <FAQAccordion faqs={data.faqs} />
        </section>

        {/* More Alternatives to Consider */}
        {relatedAlternatives.length > 0 && (
          <section className="mb-16">
            <h2 className="mb-6 text-3xl font-semibold text-white">
              {t("alternatives.more_alternatives")}
            </h2>
            <div className="grid gap-4 sm:grid-cols-3">
              {relatedAlternatives.map((alt) => (
                <Link
                  key={alt.slug}
                  href={`/alternative-to/${alt.slug}`}
                  className="group rounded-2xl bg-zinc-800 p-5 transition-all hover:bg-zinc-700/50"
                >
                  <h3 className="mb-1 text-base font-medium text-white group-hover:text-primary">
                    {t("alternatives.best_alternative", { name: alt.name })}
                  </h3>
                  <p className="text-xs text-zinc-400">{alt.tagline}</p>
                </Link>
              ))}
            </div>
          </section>
        )}

        {/* People Also Consider */}
        {relatedComparisons.length >= 1 && (
          <section className="mb-16">
            <h2 className="mb-6 text-3xl font-semibold text-white">
              {t("alternatives.people_also_consider")}
            </h2>
            <div className="grid gap-4 sm:grid-cols-3">
              {relatedComparisons.map((comp) => (
                <Link
                  key={comp.slug}
                  href={`/compare/${comp.slug}`}
                  className="group rounded-2xl bg-zinc-800 p-5 transition-all hover:bg-zinc-700/50"
                >
                  <h3 className="mb-1 text-base font-medium text-white group-hover:text-primary">
                    {t("alternatives.gaia_vs_name", { name: comp.name })}
                  </h3>
                  <p className="text-xs text-zinc-400">{comp.tagline}</p>
                </Link>
              ))}
            </div>
          </section>
        )}

        {/* Cross-link to comparison page */}
        {hasComparisonPage && (
          <section className="mb-16 border-t border-zinc-800 pt-8">
            <p className="text-sm text-zinc-500">
              {t("alternatives.want_comparison")}{" "}
              <Link
                href={`/compare/${slug}`}
                className="text-zinc-400 underline underline-offset-2 hover:text-zinc-200"
              >
                {t("alternatives.see_comparison", { name: data.name })} &rarr;
              </Link>
            </p>
          </section>
        )}

        {/* Explore more */}
        <section className="mb-16">
          <h2 className="mb-6 text-3xl font-semibold text-white">
            {t("common.explore_more")}
          </h2>
          <div className="grid gap-4 sm:grid-cols-2">
            <Link
              href="/compare"
              className="group rounded-2xl bg-zinc-800 p-5 transition-all hover:bg-zinc-700/50"
            >
              <h3 className="mb-2 text-lg font-medium text-white transition-colors group-hover:text-primary">
                {t("alternatives.gaia_vs_competitors")}
              </h3>
              <p className="text-sm leading-relaxed text-zinc-400">
                {t("alternatives.gaia_vs_competitors_desc")}
              </p>
            </Link>
            <Link
              href="/for"
              className="group rounded-2xl bg-zinc-800 p-5 transition-all hover:bg-zinc-700/50"
            >
              <h3 className="mb-2 text-lg font-medium text-white transition-colors group-hover:text-primary">
                {t("alternatives.gaia_for_role")}
              </h3>
              <p className="text-sm leading-relaxed text-zinc-400">
                {t("alternatives.gaia_for_role_desc")}
              </p>
            </Link>
          </div>
        </section>
      </article>

      <FinalSection />
    </>
  );
}
