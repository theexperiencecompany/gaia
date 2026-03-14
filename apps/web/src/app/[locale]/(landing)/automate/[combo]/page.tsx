import { Button } from "@heroui/button";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { getTranslations, setRequestLocale } from "next-intl/server";
import FAQAccordion from "@/components/seo/FAQAccordion";
import JsonLd from "@/components/seo/JsonLd";
import { getAllComboSlugs } from "@/features/integrations/data/combosData";
import {
  getTranslatedCombo,
  getTranslatedCombos,
} from "@/features/integrations/data/getTranslatedCombo";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import { getAlternates } from "@/i18n/getAlternates";
import {
  generateBreadcrumbSchema,
  generateFAQSchema,
  generateHowToSchema,
  generatePageMetadata,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";

interface PageProps {
  readonly params: Promise<{
    readonly locale: string;
    readonly combo: string;
  }>;
}

export async function generateStaticParams() {
  return getAllComboSlugs().map((slug) => ({ combo: slug }));
}

export const dynamicParams = false;

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const { combo } = await params;
  const data = await getTranslatedCombo(combo);

  if (!data) {
    return { title: "Integration Not Found" };
  }

  const metadata = generatePageMetadata({
    title: data.metaTitle,
    description: data.metaDescription,
    path: `/automate/${combo}`,
    canonicalPath: data.canonicalSlug
      ? `/automate/${data.canonicalSlug}`
      : undefined,
    keywords: data.keywords,
  });
  return {
    ...metadata,
    alternates: {
      ...metadata.alternates,
      languages: getAlternates(`/automate/${combo}`),
    },
  };
}

export default async function AutomateComboPage({ params }: PageProps) {
  const { locale, combo } = await params;
  setRequestLocale(locale);
  const [t, data, allCombos] = await Promise.all([
    getTranslations(),
    getTranslatedCombo(combo),
    getTranslatedCombos(),
  ]);

  if (!data) {
    notFound();
  }
  const relatedCombos = allCombos
    .filter(
      (c) =>
        !c.canonicalSlug &&
        c.slug !== combo &&
        (c.toolASlug === data.toolASlug ||
          c.toolBSlug === data.toolBSlug ||
          c.toolASlug === data.toolBSlug ||
          c.toolBSlug === data.toolASlug),
    )
    .slice(0, 3);

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

  return (
    <>
      <JsonLd
        data={[webPageSchema, breadcrumbSchema, howToSchema, faqSchema]}
      />

      <article className="mx-auto max-w-4xl px-6 pt-36 pb-24">
        {/* Breadcrumb */}
        <nav className="mb-8 text-sm text-zinc-500">
          <Link href="/" className="hover:text-zinc-300">
            {t("common.home")}
          </Link>
          <span className="mx-2">/</span>
          <Link href="/marketplace" className="hover:text-zinc-300">
            {t("marketplace.breadcrumb")}
          </Link>
          <span className="mx-2">/</span>
          <span className="text-zinc-300">
            {data.toolA} + {data.toolB}
          </span>
        </nav>

        {/* Hero */}
        <header className="mb-16">
          <div className="mb-4 flex flex-wrap items-center gap-3">
            <span className="inline-flex items-center rounded-full bg-zinc-800 px-3 py-1 text-xs font-medium text-zinc-400">
              {t("common.integration")}
            </span>
            <span className="inline-flex items-center rounded-full bg-primary/10 px-3 py-1 text-xs font-medium text-primary">
              {t("common.powered_by_gaia")}
            </span>
          </div>
          <h1 className="mb-4 font-serif text-5xl font-normal text-white md:text-6xl">
            {t("automate.automate_with_gaia", {
              toolA: data.toolA,
              toolB: data.toolB,
            })}
          </h1>
          <p className="text-xl leading-relaxed text-zinc-400">
            {data.tagline}
          </p>
        </header>

        {/* Intro */}
        <section className="mb-16">
          {data.intro.split("\n\n").map((paragraph) => (
            <p
              key={paragraph.slice(0, 40)}
              className="mb-4 text-lg leading-relaxed text-zinc-300 last:mb-0"
            >
              {paragraph}
            </p>
          ))}
        </section>

        {/* Use Cases */}
        <section className="mb-16">
          <h2 className="mb-2 text-3xl font-semibold text-white">
            {data.useCases.length} {t("automate.things_you_can_automate")}
          </h2>
          <p className="mb-8 text-zinc-400">
            {t("automate.everything_gaia_can_do", {
              toolA: data.toolA,
              toolB: data.toolB,
            })}
          </p>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {data.useCases.map((useCase, index) => (
              <div
                key={useCase.title}
                className="rounded-2xl bg-zinc-800 p-5 transition-colors hover:bg-zinc-700/50"
              >
                <div className="mb-3 flex items-start gap-3">
                  <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/20 text-sm font-semibold text-primary">
                    {index + 1}
                  </span>
                  <h3 className="text-base font-semibold text-white">
                    {useCase.title}
                  </h3>
                </div>
                <p className="text-sm leading-relaxed text-zinc-400">
                  {useCase.description}
                </p>
              </div>
            ))}
          </div>
        </section>

        {/* How It Works */}
        <section className="mb-16">
          <h2 className="mb-2 text-3xl font-semibold text-white">
            {t("automate.how_to_set_it_up")}
          </h2>
          <p className="mb-8 text-zinc-400">
            {t("automate.connect_in_steps", {
              toolA: data.toolA,
              toolB: data.toolB,
            })}
          </p>
          <ol className="space-y-6">
            {data.howItWorks.map((step, index) => (
              <li key={step.step} className="flex gap-5">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-primary/20 font-semibold text-primary">
                  {index + 1}
                </div>
                <div>
                  <h3 className="mb-1 text-lg font-semibold text-white">
                    {step.step}
                  </h3>
                  <p className="leading-relaxed text-zinc-400">
                    {step.description}
                  </p>
                </div>
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

        {/* Integration Links */}
        <section className="mb-16">
          <h2 className="mb-6 text-2xl font-semibold text-white">
            {t("automate.explore_integrations")}
          </h2>
          <div className="grid gap-4 sm:grid-cols-2">
            <Link
              href={`/marketplace?search=${encodeURIComponent(data.toolA)}`}
              className="group rounded-2xl bg-zinc-800 p-5 transition-all hover:bg-zinc-700/50"
            >
              <h3 className="mb-2 text-lg font-medium text-white transition-colors group-hover:text-primary">
                {t("automate.tool_integration", { tool: data.toolA })}
              </h3>
              <p className="text-sm leading-relaxed text-zinc-400">
                {t("automate.see_everything_gaia", { tool: data.toolA })}
              </p>
            </Link>
            <Link
              href={`/marketplace?search=${encodeURIComponent(data.toolB)}`}
              className="group rounded-2xl bg-zinc-800 p-5 transition-all hover:bg-zinc-700/50"
            >
              <h3 className="mb-2 text-lg font-medium text-white transition-colors group-hover:text-primary">
                {t("automate.tool_integration", { tool: data.toolB })}
              </h3>
              <p className="text-sm leading-relaxed text-zinc-400">
                {t("automate.discover_automations", { tool: data.toolB })}
              </p>
            </Link>
          </div>
        </section>

        {/* Related Automations */}
        {relatedCombos.length > 0 && (
          <section className="mb-16">
            <h2 className="mb-6 text-2xl font-semibold text-white">
              {t("common.related_automations")}
            </h2>
            <div className="grid gap-4 sm:grid-cols-3">
              {relatedCombos.map((related) => (
                <Link
                  key={related.slug}
                  href={`/automate/${related.slug}`}
                  className="group rounded-2xl bg-zinc-800 p-5 transition-all hover:bg-zinc-700/50"
                >
                  <h3 className="mb-1 text-base font-medium text-white group-hover:text-primary">
                    {related.toolA} + {related.toolB}
                  </h3>
                  <p className="text-xs text-zinc-400">{related.tagline}</p>
                </Link>
              ))}
            </div>
          </section>
        )}

        {/* More Combos Link */}
        <section className="mb-16">
          <div className="rounded-3xl bg-zinc-800 p-8">
            <h2 className="mb-3 text-2xl font-semibold text-white">
              {t("automate.explore_more_combos")}
            </h2>
            <p className="mb-6 leading-relaxed text-zinc-400">
              {t("automate.gaia_supports_combos")}
            </p>
            <Button as="a" href="/marketplace" color="primary" radius="full">
              {t("common.browse_marketplace")}
            </Button>
          </div>
        </section>
      </article>

      <FinalSection />
    </>
  );
}
