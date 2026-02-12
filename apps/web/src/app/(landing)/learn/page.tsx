import type { Metadata } from "next";
import Link from "next/link";

import FinalSection from "@/features/landing/components/sections/FinalSection";
import JsonLd from "@/components/seo/JsonLd";
import {
  getAllGlossaryTerms,
  getGlossaryTermsByCategory,
} from "@/features/glossary/data/glossaryData";
import {
  generateBreadcrumbSchema,
  generateItemListSchema,
  generatePageMetadata,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";

export const metadata: Metadata = generatePageMetadata({
  title: "AI & Productivity Glossary - Learn Key Concepts",
  description:
    "Learn essential AI, automation, and productivity concepts. Understand how AI agents, LangGraph, MCP, vector embeddings, and workflow automation power modern productivity tools like GAIA.",
  path: "/learn",
  keywords: [
    "AI glossary",
    "AI terminology",
    "productivity glossary",
    "AI concepts explained",
    "automation glossary",
    "AI agent definition",
    "LangGraph explained",
    "MCP explained",
    "workflow automation glossary",
  ],
});

const CATEGORY_LABELS: Record<string, string> = {
  "ai-concepts": "AI Concepts",
  productivity: "Productivity",
  automation: "Automation",
  infrastructure: "Infrastructure",
  integrations: "Integrations",
};

const CATEGORY_ORDER = [
  "ai-concepts",
  "productivity",
  "automation",
  "infrastructure",
  "integrations",
];

export default function LearnHubPage() {
  const allTerms = getAllGlossaryTerms();

  const webPageSchema = generateWebPageSchema(
    "AI & Productivity Glossary",
    "Learn essential AI, automation, and productivity concepts used in modern tools like GAIA.",
    `${siteConfig.url}/learn`,
    [
      { name: "Home", url: siteConfig.url },
      {
        name: "Glossary",
        url: `${siteConfig.url}/learn`,
      },
    ],
  );

  const breadcrumbSchema = generateBreadcrumbSchema([
    { name: "Home", url: siteConfig.url },
    { name: "Glossary", url: `${siteConfig.url}/learn` },
  ]);

  const itemListSchema = generateItemListSchema(
    allTerms.map((t) => ({
      name: t.term,
      url: `${siteConfig.url}/learn/${t.slug}`,
      description: t.definition,
    })),
    "Article",
  );

  return (
    <>
      <JsonLd
        data={[
          webPageSchema,
          breadcrumbSchema,
          itemListSchema,
        ]}
      />

      <div className="mx-auto max-w-5xl px-6 pt-36 pb-24">
        <header className="mb-16 text-center">
          <h1 className="mb-4 font-serif text-5xl font-normal text-white md:text-6xl">
            AI &amp; Productivity Glossary
          </h1>
          <p className="mx-auto max-w-2xl text-xl text-zinc-400">
            Understand the key concepts behind AI agents,
            automation, and modern productivity tools.
            Learn how GAIA uses these technologies to
            manage your digital workflow.
          </p>
        </header>

        {CATEGORY_ORDER.map((categoryKey) => {
          const terms =
            getGlossaryTermsByCategory(categoryKey);
          if (terms.length === 0) return null;

          return (
            <section key={categoryKey} className="mb-14">
              <h2 className="mb-6 text-2xl font-semibold text-white">
                {CATEGORY_LABELS[categoryKey] ??
                  categoryKey}
              </h2>

              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {terms.map((term) => (
                  <Link
                    key={term.slug}
                    href={`/learn/${term.slug}`}
                    className="group flex flex-col gap-2 rounded-3xl bg-zinc-800 p-5 transition-all hover:bg-zinc-700/50"
                  >
                    <h3 className="mb-2 text-lg font-semibold text-white transition-colors group-hover:text-primary">
                      {term.term}
                    </h3>
                    <p className="line-clamp-3 text-sm leading-relaxed text-zinc-400">
                      {term.definition}
                    </p>
                  </Link>
                ))}
              </div>
            </section>
          );
        })}

      </div>

      <FinalSection />
    </>
  );
}
