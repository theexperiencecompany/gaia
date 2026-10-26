import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getTranslations, setRequestLocale } from "next-intl/server";
import DocsGuidesSection from "@/components/seo/DocsGuidesSection";
import FAQAccordion from "@/components/seo/FAQAccordion";
import JsonLd from "@/components/seo/JsonLd";
import { PageBreadcrumbs } from "@/components/seo/PageBreadcrumbs";
import { ProseParagraphs } from "@/components/seo/ProseParagraphs";
import { RelatedAutomationsGrid } from "@/components/seo/RelatedAutomationsGrid";
import { RelatedComparisonsGrid } from "@/components/seo/RelatedComparisonsGrid";
import { SiteLink } from "@/components/seo/SiteLink";
import { getTranslatedGlossaryTerm } from "@/features/glossary/data/getTranslatedGlossary";
import { getAllGlossaryTermSlugs } from "@/features/glossary/data/glossaryData";
import { getTranslatedCombo } from "@/features/integrations/data/getTranslatedCombo";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import { generateLocalizedPageMetadata } from "@/i18n/getAlternates";
import { LEARN_DOCS_LINKS } from "@/lib/docs-links";
import { prerenderedMarketingParams } from "@/lib/selfhost";
import {
  generateBreadcrumbSchema,
  generateDefinedTermSchema,
  generateFAQSchema,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";

interface PageProps {
  readonly params: Promise<{
    readonly locale: string;
    readonly term: string;
  }>;
}

async function allStaticParams() {
  const slugs = await getAllGlossaryTermSlugs();
  return slugs.map((term) => ({ term }));
}

export function generateStaticParams() {
  return prerenderedMarketingParams(allStaticParams);
}

export const dynamicParams = false;

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const { locale, term } = await params;
  const data = await getTranslatedGlossaryTerm(term);

  if (!data) {
    return { title: "Term Not Found" };
  }

  return generateLocalizedPageMetadata({
    title: data.metaTitle,
    description: data.metaDescription,
    path: `/learn/${term}`,
    keywords: data.keywords,
    locale,
  });
}

export default async function GlossaryTermPage({ params }: PageProps) {
  const { locale, term } = await params;
  setRequestLocale(locale);
  const [t, data] = await Promise.all([
    getTranslations(),
    getTranslatedGlossaryTerm(term),
  ]);

  if (!data) {
    notFound();
  }

  const webPageSchema = generateWebPageSchema(
    data.metaTitle,
    data.metaDescription,
    `${siteConfig.url}/learn/${term}`,
    [
      { name: "Home", url: siteConfig.url },
      {
        name: "Glossary",
        url: `${siteConfig.url}/learn`,
      },
      {
        name: data.term,
        url: `${siteConfig.url}/learn/${term}`,
      },
    ],
  );

  const breadcrumbSchema = generateBreadcrumbSchema([
    { name: "Home", url: siteConfig.url },
    { name: "Glossary", url: `${siteConfig.url}/learn` },
    {
      name: data.term,
      url: `${siteConfig.url}/learn/${term}`,
    },
  ]);

  const faqSchema = generateFAQSchema(data.faqs);

  const definedTermSchema = generateDefinedTermSchema(
    data.term,
    data.definition,
    `${siteConfig.url}/learn/${term}`,
  );

  const docsGuides = LEARN_DOCS_LINKS[term] ?? [];

  const [relatedTerms, relatedAutomations] = await Promise.all([
    Promise.all(
      data.relatedTerms.map((slug) => getTranslatedGlossaryTerm(slug)),
    ).then((results) =>
      results.filter(
        (glossaryTerm): glossaryTerm is NonNullable<typeof glossaryTerm> =>
          glossaryTerm !== undefined,
      ),
    ),
    Promise.all(
      (data.relatedAutomations ?? []).map((slug) => getTranslatedCombo(slug)),
    ).then((results) =>
      results.filter(
        (combo): combo is NonNullable<typeof combo> => combo !== undefined,
      ),
    ),
  ]);

  return (
    <>
      <JsonLd
        data={[webPageSchema, breadcrumbSchema, faqSchema, definedTermSchema]}
      />

      <article className="mx-auto max-w-4xl px-6 pt-36 pb-24">
        <PageBreadcrumbs
          className="mb-8"
          items={[
            { label: t("common.home"), href: "/" },
            { label: t("glossary.breadcrumb"), href: "/learn" },
            { label: data.term },
          ]}
        />

        {/* Definition Hero */}
        <header className="mb-16">
          <h1 className="mb-6 font-serif text-5xl font-normal text-white md:text-6xl">
            {data.term}
          </h1>
          <div className="rounded-3xl bg-zinc-800 p-8">
            <p className="text-xl leading-relaxed text-zinc-200">
              {data.definition}
            </p>
          </div>
        </header>

        {/* Extended Description */}
        <section className="mb-16">
          <h2 className="mb-4 text-3xl font-semibold text-white">
            {t("glossary.understanding")} {data.term}
          </h2>
          <ProseParagraphs
            text={data.extendedDescription}
            className="text-lg leading-relaxed text-zinc-300"
          />
        </section>

        {/* How GAIA Uses It */}
        <section className="mb-16 rounded-3xl bg-zinc-800 p-8">
          <h2 className="mb-4 text-2xl font-semibold text-emerald-400">
            {t("glossary.how_gaia_uses")} {data.term}
          </h2>
          <ProseParagraphs
            text={data.howGaiaUsesIt}
            className="text-lg leading-relaxed text-zinc-300"
          />
        </section>

        {/* Related Terms */}
        {relatedTerms.length > 0 && (
          <section className="mb-16">
            <h2 className="mb-6 text-3xl font-semibold text-white">
              {t("glossary.related_concepts")}
            </h2>
            <div className="grid gap-4 sm:grid-cols-2">
              {relatedTerms.map((related) => (
                <SiteLink
                  key={related.slug}
                  href={`/learn/${related.slug}`}
                  className="group rounded-2xl bg-zinc-800 p-5 transition-colors hover:bg-zinc-700/50"
                >
                  <h3 className="mb-2 text-lg font-medium text-white transition-colors group-hover:text-primary">
                    {related.term}
                  </h3>
                  <p className="line-clamp-2 text-sm leading-relaxed text-zinc-400">
                    {related.definition}
                  </p>
                </SiteLink>
              ))}
            </div>
          </section>
        )}

        {/* FAQ */}
        <section className="mb-16">
          <h2 className="mb-6 text-3xl font-semibold text-white">
            {t("common.faq")}
          </h2>
          <FAQAccordion faqs={data.faqs} />
        </section>

        {/* Tools That Use This Term */}
        <RelatedComparisonsGrid
          heading={t("glossary.tools_that_use", { term: data.term })}
          slugs={data.relatedComparisons ?? []}
        />

        <RelatedAutomationsGrid
          heading={t("common.related_automations")}
          combos={relatedAutomations}
        />

        <DocsGuidesSection
          heading={t("common.docs_guides")}
          guides={docsGuides}
        />

        {/* Explore More */}
        <section className="mb-16">
          <h2 className="mb-6 text-3xl font-semibold text-white">
            {t("common.explore_more")}
          </h2>
          <div className="grid gap-4 sm:grid-cols-2">
            <SiteLink
              href="/compare"
              className="group rounded-2xl bg-zinc-800 p-5 transition-colors hover:bg-zinc-700/50"
            >
              <h3 className="mb-2 text-lg font-medium text-white transition-colors group-hover:text-primary">
                {t("glossary.compare_alternatives")}
              </h3>
              <p className="text-sm leading-relaxed text-zinc-400">
                {t("glossary.compare_alternatives_desc")}
              </p>
            </SiteLink>
            <SiteLink
              href="/for"
              className="group rounded-2xl bg-zinc-800 p-5 transition-colors hover:bg-zinc-700/50"
            >
              <h3 className="mb-2 text-lg font-medium text-white transition-colors group-hover:text-primary">
                {t("glossary.gaia_for_role")}
              </h3>
              <p className="text-sm leading-relaxed text-zinc-400">
                {t("glossary.gaia_for_role_desc")}
              </p>
            </SiteLink>
          </div>
        </section>
      </article>

      <FinalSection />
    </>
  );
}
