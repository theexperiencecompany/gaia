import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import FAQAccordion from "@/components/seo/FAQAccordion";
import JsonLd from "@/components/seo/JsonLd";
import { getAlternative } from "@/features/alternatives/data/alternativesData";
import {
  getAllComparisons,
  getAllComparisonSlugs,
  getComparison,
} from "@/features/comparisons/data/comparisonsData";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import {
  generateBreadcrumbSchema,
  generateFAQSchema,
  generatePageMetadata,
  generateProductSchema,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";

interface PageProps {
  params: Promise<{ slug: string }>;
}

export async function generateStaticParams() {
  return getAllComparisonSlugs().map((slug) => ({ slug }));
}

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const { slug } = await params;
  const data = getComparison(slug);

  if (!data) {
    return { title: "Comparison Not Found" };
  }

  return generatePageMetadata({
    title: data.metaTitle,
    description: data.metaDescription,
    path: `/compare/${slug}`,
    keywords: data.keywords,
  });
}

const COMPARISON_CATEGORIES: Record<string, string> = {
  // AI Assistants
  chatgpt: "AI Assistants",
  "chatgpt-teams": "AI Assistants",
  claude: "AI Assistants",
  gemini: "AI Assistants",
  copilot: "AI Assistants",
  "cursor-ai": "AI Assistants",
  "google-assistant": "AI Assistants",
  perplexity: "AI Assistants",
  "lindy-ai": "AI Assistants",
  "limitless-ai": "AI Assistants",
  "rewind-ai": "AI Assistants",
  "martin-ai": "AI Assistants",
  poke: "AI Assistants",
  "mem-ai": "AI Assistants",
  // Automation
  zapier: "Automation",
  n8n: "Automation",
  make: "Automation",
  bardeen: "Automation",
  activepieces: "Automation",
  pipedream: "Automation",
  relay: "Automation",
  // Task Management
  todoist: "Task Management",
  ticktick: "Task Management",
  things3: "Task Management",
  anydo: "Task Management",
  omnifocus: "Task Management",
  // Project Management
  asana: "Project Management",
  clickup: "Project Management",
  jira: "Project Management",
  linear: "Project Management",
  trello: "Project Management",
  height: "Project Management",
  monday: "Project Management",
  basecamp: "Project Management",
  // Calendar & Scheduling
  "google-calendar": "Calendar & Scheduling",
  fantastical: "Calendar & Scheduling",
  "notion-calendar": "Calendar & Scheduling",
  clockwise: "Calendar & Scheduling",
  reclaim: "Calendar & Scheduling",
  motion: "Calendar & Scheduling",
  cal: "Calendar & Scheduling",
  savvycal: "Calendar & Scheduling",
  calendly: "Calendar & Scheduling",
  akiflow: "Calendar & Scheduling",
  // Email
  superhuman: "Email",
  sanebox: "Email",
  shortwave: "Email",
  "hey-email": "Email",
  missive: "Email",
  spark: "Email",
  // Notes & Knowledge
  notion: "Notes & Knowledge",
  obsidian: "Notes & Knowledge",
  logseq: "Notes & Knowledge",
  "roam-research": "Notes & Knowledge",
  evernote: "Notes & Knowledge",
  craft: "Notes & Knowledge",
  "reflect-app": "Notes & Knowledge",
  capacities: "Notes & Knowledge",
  tana: "Notes & Knowledge",
  "notion-ai": "Notes & Knowledge",
  // Task Management (additional)
  "apple-reminders": "Task Management",
  sunsama: "Calendar & Scheduling",
  openclaw: "Automation",
};

function ComparisonTableRow({
  feature,
  gaia,
  competitor,
}: {
  feature: string;
  gaia: string;
  competitor: string;
}) {
  return (
    <tr className="border-b border-zinc-700/50 transition-colors hover:bg-white/[0.02]">
      <td className="px-4 py-4 text-sm font-medium text-zinc-300">{feature}</td>
      <td className="px-4 py-4 text-sm text-emerald-400">{gaia}</td>
      <td className="px-4 py-4 text-sm text-zinc-400">{competitor}</td>
    </tr>
  );
}

export default async function ComparisonPage({ params }: PageProps) {
  const { slug } = await params;
  const data = getComparison(slug);

  if (!data) {
    notFound();
  }

  const hasAlternativePage = getAlternative(slug) !== undefined;

  const currentCategory = COMPARISON_CATEGORIES[slug] ?? "Other";
  const relatedComparisons = getAllComparisons()
    .filter(
      (c) =>
        c.slug !== slug && COMPARISON_CATEGORIES[c.slug] === currentCategory,
    )
    .slice(0, 3);

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
      <JsonLd data={[webPageSchema, breadcrumbSchema, faqSchema, productSchema]} />

      <article className="mx-auto max-w-4xl px-6 pt-36 pb-24">
        {/* Breadcrumb */}
        <nav className="mb-8 text-sm text-zinc-500">
          <Link href="/" className="hover:text-zinc-300">
            Home
          </Link>
          <span className="mx-2">/</span>
          <Link href="/compare" className="hover:text-zinc-300">
            Comparisons
          </Link>
          <span className="mx-2">/</span>
          <span className="text-zinc-300">GAIA vs {data.name}</span>
        </nav>

        {/* Hero */}
        <header className="mb-16">
          <h1 className="mb-4 font-serif text-5xl font-normal text-white md:text-6xl">
            GAIA vs {data.name}
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
            Feature Comparison
          </h2>
          <div className="overflow-x-auto rounded-3xl bg-zinc-800">
            <table className="w-full">
              <thead>
                <tr className="border-b border-zinc-700">
                  <th className="px-4 py-4 text-left text-sm font-medium text-zinc-500">
                    Feature
                  </th>
                  <th className="px-4 py-4 text-left text-sm font-medium text-primary">
                    GAIA
                  </th>
                  <th className="px-4 py-4 text-left text-sm font-medium text-zinc-400">
                    {data.name}
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row) => (
                  <ComparisonTableRow
                    key={row.feature}
                    feature={row.feature}
                    gaia={row.gaia}
                    competitor={row.competitor}
                  />
                ))}
              </tbody>
            </table>
          </div>
        </section>

        {/* Advantages */}
        <div className="mb-16 grid gap-8 md:grid-cols-2">
          <section>
            <h2 className="mb-4 text-2xl font-semibold text-emerald-400">
              Why Choose GAIA
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
              Where {data.name} Excels
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
            The Verdict
          </h2>
          <p className="text-lg leading-relaxed text-zinc-300">
            {data.verdict}
          </p>
        </section>

        {/* FAQ */}
        <section className="mb-16">
          <h2 className="mb-6 text-3xl font-semibold text-white">
            Frequently Asked Questions
          </h2>
          <FAQAccordion faqs={data.faqs} />
        </section>

        {/* Cross-link to alternative-to page */}
        {hasAlternativePage && (
          <section className="mb-16 border-t border-zinc-800 pt-8">
            <p className="text-sm text-zinc-500">
              Looking for the best {data.name} alternative?{" "}
              <Link
                href={`/alternative-to/${slug}`}
                className="text-zinc-400 underline underline-offset-2 hover:text-zinc-200"
              >
                See our complete guide &rarr; Best {data.name} Alternative in
                2026
              </Link>
            </p>
          </section>
        )}

        {/* Related Comparisons */}
        {relatedComparisons.length > 0 && (
          <section className="mb-16">
            <h2 className="mb-6 text-3xl font-semibold text-white">
              Compare More {currentCategory} Tools
            </h2>
            <div className="grid gap-4 sm:grid-cols-3">
              {relatedComparisons.map((comp) => (
                <Link
                  key={comp.slug}
                  href={`/compare/${comp.slug}`}
                  className="group rounded-2xl bg-zinc-800 p-5 transition-all hover:bg-zinc-700/50"
                >
                  <h3 className="mb-1 text-base font-medium text-white group-hover:text-primary">
                    GAIA vs {comp.name}
                  </h3>
                  <p className="text-xs text-zinc-400">{comp.tagline}</p>
                </Link>
              ))}
            </div>
          </section>
        )}

        {/* Explore More */}
        <section className="mb-16">
          <h2 className="mb-6 text-3xl font-semibold text-white">
            Explore More
          </h2>
          <div className="grid gap-4 sm:grid-cols-2">
            <Link
              href="/learn"
              className="group rounded-2xl bg-zinc-800 p-5 transition-all hover:bg-zinc-700/50"
            >
              <h3 className="mb-2 text-lg font-medium text-white transition-colors group-hover:text-primary">
                AI Glossary
              </h3>
              <p className="text-sm leading-relaxed text-zinc-400">
                Learn about the AI concepts and technology behind GAIA and{" "}
                {data.name}.
              </p>
            </Link>
            <Link
              href="/for"
              className="group rounded-2xl bg-zinc-800 p-5 transition-all hover:bg-zinc-700/50"
            >
              <h3 className="mb-2 text-lg font-medium text-white transition-colors group-hover:text-primary">
                GAIA for Your Role
              </h3>
              <p className="text-sm leading-relaxed text-zinc-400">
                See how GAIA helps professionals in different roles boost their
                productivity.
              </p>
            </Link>
          </div>
        </section>
      </article>
      <FinalSection />
    </>
  );
}
