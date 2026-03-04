import { Chip } from "@heroui/chip";
import { CircleArrowRight02Icon } from "@icons";
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

const FEATURED_SLUGS = new Set(["startup-founders"]);

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
            Every professional has unique workflows and pain points. GAIA adapts
            to your role, connecting the tools you already use and automating
            the tasks that drain your time.
          </p>
        </header>

        <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
          {personas
            .sort((a, b) => {
              const aFeatured = FEATURED_SLUGS.has(a.slug) ? 0 : 1;
              const bFeatured = FEATURED_SLUGS.has(b.slug) ? 0 : 1;
              return aFeatured - bFeatured;
            })
            .map((persona) => {
              const isFeatured = FEATURED_SLUGS.has(persona.slug);

              return (
                <Link
                  key={persona.slug}
                  href={`/for/${persona.slug}`}
                  className={`group flex flex-col gap-2 rounded-3xl p-5 transition-all ${
                    isFeatured
                      ? "bg-primary/10 md:col-span-2 lg:col-span-3 hover:bg-primary/15"
                      : "bg-zinc-800 hover:bg-zinc-700/50"
                  }`}
                >
                  <div className="flex items-center gap-3">
                    <h2
                      className={`text-xl font-semibold transition-colors group-hover:text-primary ${
                        isFeatured ? "text-primary" : "text-white"
                      }`}
                    >
                      {persona.role}
                    </h2>
                    {isFeatured && (
                      <Chip variant="flat" color="primary" size="sm">
                        Featured
                      </Chip>
                    )}
                  </div>
                  <p
                    className={`text-sm leading-relaxed ${isFeatured ? "max-w-2xl text-zinc-300" : "text-zinc-400"}`}
                  >
                    {persona.metaDescription}
                  </p>
                  {isFeatured && (
                    <span className="mt-1 flex items-center gap-1.5 text-sm font-medium text-primary">
                      See the full experience
                      <CircleArrowRight02Icon width={17} height={17} />
                    </span>
                  )}
                </Link>
              );
            })}
        </div>
      </div>
      <FinalSection />
    </>
  );
}
