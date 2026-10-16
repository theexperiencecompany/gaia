import Link from "next/link";
import type { ReactNode } from "react";

import ComparisonTable from "@/components/seo/ComparisonTable";
import FAQAccordion from "@/components/seo/FAQAccordion";
import JsonLd from "@/components/seo/JsonLd";
import {
  getAllAlternatives,
  getAlternative,
} from "@/features/alternatives/data/alternativesData";
import {
  type ComparisonData,
  getAllComparisons,
  getComparison,
} from "@/features/comparisons/data/comparisonsData";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import {
  generateBreadcrumbSchema,
  generateFAQSchema,
  generateItemListSchema,
  generatePageMetadata,
  generateProductSchema,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";

export interface BestHubConfig {
  readonly pagePath: string;
  readonly pageTitle: string;
  readonly pageDescription: string;
  readonly keywords: string[];
  readonly breadcrumbName: string;
  readonly heading: string;
  readonly subheading: string;
  readonly intro: ReactNode;
  readonly tableAriaLabel: string;
  readonly tableTitle: string;
  readonly gaiaBestFor: string;
  readonly gaiaTake: string;
  readonly gaiaItemDescription: string;
  readonly pickBody: string;
  readonly pickCompareHref: string;
  readonly pickCompareLabel: string;
  readonly pickAlternativeHref: string;
  readonly pickAlternativeLabel: string;
  /** Slugs in rank order, GAIA excluded. Each must resolve via getComparison. */
  readonly rankedSlugs: readonly string[];
  readonly bestFor: Record<string, string>;
  readonly shortVersion: Record<string, string>;
  readonly faqs: Array<{ question: string; answer: string }>;
  readonly comparisonsTitle: string;
  readonly alternativesTitle: string;
  /**
   * When true, the bottom link lists cover every comparison and
   * alternative guide instead of just this hub's ranked pool.
   */
  readonly listAll?: boolean;
}

export function generateBestHubMetadata(
  config: Pick<
    BestHubConfig,
    "pageTitle" | "pageDescription" | "pagePath" | "keywords"
  >,
) {
  return generatePageMetadata({
    title: config.pageTitle,
    description: config.pageDescription,
    path: config.pagePath,
    keywords: config.keywords,
  });
}

interface RankedPick {
  readonly data: ComparisonData;
  readonly hasAlternativePage: boolean;
}

export default async function BestAssistantHub({
  config,
}: {
  readonly config: BestHubConfig;
}) {
  const [picks, allComparisons, allAlternatives] = await Promise.all([
    Promise.all(
      config.rankedSlugs.map(async (slug): Promise<RankedPick | undefined> => {
        const data = await getComparison(slug);
        if (!data) return undefined;
        const alternative = await getAlternative(slug);
        return { data, hasAlternativePage: alternative !== undefined };
      }),
    ),
    getAllComparisons(),
    getAllAlternatives(),
  ]);

  const ranked: RankedPick[] = [];
  const missingSlugs: string[] = [];
  picks.forEach((pick, index) => {
    const slug = config.rankedSlugs[index];
    if (pick === undefined) {
      missingSlugs.push(slug);
    } else {
      ranked.push(pick);
    }
  });
  if (missingSlugs.length > 0) {
    throw new Error(
      `${config.pagePath}: missing comparison data for slugs: ${missingSlugs.join(", ")}`,
    );
  }

  const poolSlugs = new Set(config.rankedSlugs);
  const listedComparisons = config.listAll
    ? [...allComparisons].sort((a, b) => a.name.localeCompare(b.name))
    : allComparisons
        .filter((c) => poolSlugs.has(c.slug))
        .sort((a, b) => a.name.localeCompare(b.name));
  const listedAlternatives = config.listAll
    ? [...allAlternatives].sort((a, b) => a.name.localeCompare(b.name))
    : allAlternatives
        .filter((a) => poolSlugs.has(a.slug))
        .sort((a, b) => a.name.localeCompare(b.name));

  const pageUrl = `${siteConfig.url}${config.pagePath}`;

  const webPageSchema = generateWebPageSchema(
    config.pageTitle,
    config.pageDescription,
    pageUrl,
    [
      { name: "Home", url: siteConfig.url },
      { name: config.breadcrumbName, url: pageUrl },
    ],
  );

  const breadcrumbSchema = generateBreadcrumbSchema([
    { name: "Home", url: siteConfig.url },
    { name: config.breadcrumbName, url: pageUrl },
  ]);

  const itemListSchema = generateItemListSchema(
    [
      {
        name: "GAIA (our pick)",
        url: siteConfig.url,
        description: config.gaiaItemDescription,
      },
      ...ranked.map((pick) => ({
        name: `GAIA vs ${pick.data.name}`,
        url: `${siteConfig.url}/compare/${pick.data.slug}`,
        description: pick.data.tagline,
      })),
    ],
    "WebPage",
  );

  const faqSchema = generateFAQSchema(config.faqs);
  const totalCount = ranked.length + 1;

  return (
    <>
      <JsonLd
        data={[
          webPageSchema,
          breadcrumbSchema,
          itemListSchema,
          faqSchema,
          generateProductSchema(),
        ]}
      />

      <article className="mx-auto max-w-4xl px-6 pt-36 pb-24">
        <nav className="mb-8 text-sm text-zinc-500">
          <Link href="/" className="hover:text-zinc-300">
            Home
          </Link>
          <span className="mx-2">/</span>
          <span className="text-zinc-300">{config.breadcrumbName}</span>
        </nav>

        <header className="mb-12">
          <h1 className="mb-4 font-serif text-5xl font-normal text-white md:text-6xl">
            {config.heading}
          </h1>
          <p className="text-xl leading-relaxed text-zinc-400">
            {config.subheading}
          </p>
        </header>

        <section className="mb-16 space-y-5 text-lg leading-relaxed text-zinc-300">
          {config.intro}
        </section>

        <section className="mb-16">
          <h2 className="mb-6 text-3xl font-semibold text-white">
            {config.tableTitle}
          </h2>
          <ComparisonTable
            ariaLabel={config.tableAriaLabel}
            columns={[
              {
                key: "rank",
                label: "#",
                headerClassName: "text-zinc-500",
                cellClassName: "font-medium text-zinc-300",
              },
              {
                key: "assistant",
                label: "Assistant",
                headerClassName: "text-primary",
                cellClassName: "font-medium text-white",
              },
              {
                key: "bestFor",
                label: "Best for",
                headerClassName: "text-zinc-500",
                cellClassName: "text-zinc-300",
              },
              {
                key: "take",
                label: "The short version",
                headerClassName: "text-zinc-500",
                cellClassName: "text-zinc-400",
              },
            ]}
            rows={[
              {
                rank: "1",
                assistant: "GAIA (our pick)",
                bestFor: config.gaiaBestFor,
                take: config.gaiaTake,
              },
              ...ranked.map((pick, index) => ({
                rank: String(index + 2),
                assistant: pick.data.name,
                bestFor: config.bestFor[pick.data.slug] ?? pick.data.tagline,
                take: config.shortVersion[pick.data.slug] ?? pick.data.tagline,
              })),
            ]}
          />
        </section>

        <section className="mb-16 rounded-3xl bg-zinc-800 p-8">
          <h2 className="mb-4 text-2xl font-semibold text-white">
            Our pick: GAIA
          </h2>
          <p className="mb-4 text-lg leading-relaxed text-zinc-300">
            {config.pickBody}
          </p>
          <div className="flex flex-wrap gap-4 text-sm">
            <Link
              href={config.pickCompareHref}
              className="text-zinc-400 underline underline-offset-2 hover:text-zinc-200"
            >
              {config.pickCompareLabel}
            </Link>
            <Link
              href={config.pickAlternativeHref}
              className="text-zinc-400 underline underline-offset-2 hover:text-zinc-200"
            >
              {config.pickAlternativeLabel}
            </Link>
          </div>
        </section>

        <section className="mb-16">
          <h2 className="mb-6 text-3xl font-semibold text-white">
            The {ranked.length} runners-up, in order
          </h2>
          <ol className="mb-10 space-y-2 text-zinc-400">
            {ranked.map((pick, index) => (
              <li key={pick.data.slug}>
                <span className="mr-2 text-zinc-500">{index + 2}.</span>
                <a
                  href={`#pick-${pick.data.slug}`}
                  className="underline underline-offset-2 hover:text-zinc-200"
                >
                  {pick.data.name}
                </a>
              </li>
            ))}
          </ol>

          <div className="space-y-10">
            {ranked.map((pick, index) => (
              <section
                key={pick.data.slug}
                id={`pick-${pick.data.slug}`}
                className="scroll-mt-32 rounded-3xl bg-zinc-800 p-8"
              >
                <p className="mb-1 text-sm text-zinc-500">
                  #{index + 2} of {totalCount}
                </p>
                <h3 className="mb-1 text-2xl font-semibold text-white">
                  {pick.data.name}
                </h3>
                <p className="mb-4 text-sm text-zinc-500">
                  {pick.data.tagline}
                </p>
                <p className="mb-4 leading-relaxed text-zinc-300">
                  {pick.data.description}
                </p>
                <p className="mb-6 leading-relaxed text-zinc-400">
                  {pick.data.verdict}
                </p>
                <div className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
                  <Link
                    href={`/compare/${pick.data.slug}`}
                    className="text-zinc-300 underline underline-offset-2 hover:text-white"
                  >
                    GAIA vs {pick.data.name}: full comparison
                  </Link>
                  {pick.hasAlternativePage && (
                    <Link
                      href={`/alternative-to/${pick.data.slug}`}
                      className="text-zinc-300 underline underline-offset-2 hover:text-white"
                    >
                      Best {pick.data.name} alternative guide
                    </Link>
                  )}
                </div>
              </section>
            ))}
          </div>
        </section>

        <section className="mb-16">
          <h2 className="mb-6 text-3xl font-semibold text-white">
            Common questions
          </h2>
          <FAQAccordion faqs={config.faqs} />
        </section>

        <section className="mb-16">
          <h2 className="mb-4 text-3xl font-semibold text-white">
            {config.comparisonsTitle}
          </h2>
          <p className="mb-6 leading-relaxed text-zinc-400">
            We publish a full head-to-head for each tool below. Start from the{" "}
            <Link
              href="/compare"
              className="underline underline-offset-2 hover:text-zinc-200"
            >
              comparisons hub
            </Link>{" "}
            or jump straight in:
          </p>
          <ul className="columns-2 gap-6 text-sm leading-loose text-zinc-400 sm:columns-3">
            {listedComparisons.map((comparison) => (
              <li key={comparison.slug} className="break-inside-avoid">
                <Link
                  href={`/compare/${comparison.slug}`}
                  className="hover:text-zinc-200 hover:underline hover:underline-offset-2"
                >
                  GAIA vs {comparison.name}
                </Link>
              </li>
            ))}
          </ul>
        </section>

        <section className="mb-16">
          <h2 className="mb-4 text-3xl font-semibold text-white">
            {config.alternativesTitle}
          </h2>
          <p className="mb-6 leading-relaxed text-zinc-400">
            Migration-focused guides with fit scores and switch steps. Browse
            the{" "}
            <Link
              href="/alternative-to"
              className="underline underline-offset-2 hover:text-zinc-200"
            >
              alternatives hub
            </Link>{" "}
            or jump straight in:
          </p>
          <ul className="columns-2 gap-6 text-sm leading-loose text-zinc-400 sm:columns-3">
            {listedAlternatives.map((alternative) => (
              <li key={alternative.slug} className="break-inside-avoid">
                <Link
                  href={`/alternative-to/${alternative.slug}`}
                  className="hover:text-zinc-200 hover:underline hover:underline-offset-2"
                >
                  Best {alternative.name} alternative
                </Link>
              </li>
            ))}
          </ul>
        </section>
      </article>
      <FinalSection />
    </>
  );
}
