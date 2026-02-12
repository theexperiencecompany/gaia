import type { Metadata } from "next";
import Link from "next/link";

import JsonLd from "@/components/seo/JsonLd";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import { getAllPersonas } from "@/features/personas/data/personasData";
import {
  generateBreadcrumbSchema,
  generateItemListSchema,
  generatePageMetadata,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";

export const metadata: Metadata = generatePageMetadata({
  title: "GAIA for Every Role - AI Assistant for Professionals",
  description:
    "Discover how GAIA helps software developers, product managers, founders, marketers, and 20+ other roles automate their workflows and boost productivity with AI.",
  path: "/for",
  keywords: [
    "AI assistant for professionals",
    "role-based AI assistant",
    "AI productivity by role",
    "GAIA use cases by profession",
    "AI assistant for teams",
    "professional AI automation",
  ],
});

export default function PersonasHubPage() {
  const personas = getAllPersonas();

  const webPageSchema = generateWebPageSchema(
    "GAIA for Every Role",
    "Discover how GAIA helps professionals across every role automate their workflows and boost productivity.",
    `${siteConfig.url}/for`,
    [
      { name: "Home", url: siteConfig.url },
      { name: "GAIA for Every Role", url: `${siteConfig.url}/for` },
    ],
  );

  const breadcrumbSchema = generateBreadcrumbSchema([
    { name: "Home", url: siteConfig.url },
    { name: "GAIA for Every Role", url: `${siteConfig.url}/for` },
  ]);

  const itemListSchema = generateItemListSchema(
    personas.map((p) => ({
      name: p.title,
      url: `${siteConfig.url}/for/${p.slug}`,
      description: p.metaDescription,
    })),
    "Article",
  );

  return (
    <>
      <JsonLd data={[webPageSchema, breadcrumbSchema, itemListSchema]} />

      <div className="mx-auto max-w-5xl px-6 pt-36 pb-24">
        <header className="mb-16 text-center">
          <h1 className="mb-4 font-serif text-5xl font-normal text-white md:text-6xl">
            GAIA for Every Role
          </h1>
          <p className="mx-auto max-w-2xl text-xl text-zinc-400">
            Every professional has unique workflows and pain points. GAIA
            adapts to your role, connecting the tools you already use and
            automating the tasks that drain your time.
          </p>
        </header>

        <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
          {personas.map((persona) => (
            <Link
              key={persona.slug}
              href={`/for/${persona.slug}`}
              className="group flex flex-col gap-2 rounded-3xl bg-zinc-800 p-5 transition-all hover:bg-zinc-700/50"
            >
              <h2 className="mb-2 text-xl font-semibold text-white transition-colors group-hover:text-primary">
                {persona.role}
              </h2>
              <p className="text-sm leading-relaxed text-zinc-400">
                {persona.metaDescription}
              </p>
            </Link>
          ))}
        </div>

      </div>
      <FinalSection />
    </>
  );
}
