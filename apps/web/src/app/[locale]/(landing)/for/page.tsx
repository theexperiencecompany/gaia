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

const FEATURED_SLUGS = new Set([
  "startup-founders",
  "software-developers",
  "sales-professionals",
  "product-managers",
  "engineering-managers",
  "agency-owners",
]);

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

  const heroPersona = personas.find((p) => p.slug === "startup-founders");
  const featuredPersonas = personas.filter(
    (p) => FEATURED_SLUGS.has(p.slug) && p.slug !== "startup-founders",
  );
  const otherPersonas = personas.filter((p) => !FEATURED_SLUGS.has(p.slug));

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

        {/* Featured Experiences */}
        <section className="mb-16">
          <p className="mb-4 text-[11px] font-semibold uppercase tracking-widest text-zinc-500">
            Featured Experiences
          </p>

          {/* Hero card */}
          {heroPersona && (
            <Link
              href="/for/startup-founders"
              className="group mb-4 flex flex-col gap-3 rounded-3xl bg-primary/10 p-6 transition-all hover:bg-primary/15"
            >
              <div className="flex items-center gap-3">
                <h2 className="text-2xl font-semibold text-primary">
                  {heroPersona.role}
                </h2>
              </div>
              <p className="max-w-2xl text-sm leading-relaxed text-zinc-300">
                {heroPersona.metaDescription}
              </p>
              <span className="flex items-center gap-1.5 text-sm font-medium text-primary">
                See the full experience
                <CircleArrowRight02Icon width={17} height={17} />
              </span>
            </Link>
          )}

          {/* Other featured */}
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {featuredPersonas.map((persona) => (
              <Link
                key={persona.slug}
                href={`/for/${persona.slug}`}
                className="group flex flex-col gap-2 rounded-3xl bg-primary/10 p-5 transition-all hover:bg-primary/15"
              >
                <h2 className="text-xl font-semibold text-primary transition-colors">
                  {persona.role}
                </h2>
                <p className="flex-1 text-sm leading-relaxed text-zinc-300">
                  {persona.metaDescription}
                </p>
                <span className="mt-1 flex items-center gap-1.5 text-sm font-medium text-primary">
                  See the full experience
                  <CircleArrowRight02Icon width={17} height={17} />
                </span>
              </Link>
            ))}
          </div>
        </section>

        {/* All other roles */}
        {otherPersonas.length > 0 && (
          <section>
            <p className="mb-4 text-[11px] font-semibold uppercase tracking-widest text-zinc-500">
              All Roles
            </p>
            <div className="grid gap-3 sm:grid-cols-2 md:grid-cols-3">
              {otherPersonas.map((persona) => (
                <Link
                  key={persona.slug}
                  href={`/for/${persona.slug}`}
                  className="group flex flex-col gap-2 rounded-3xl bg-zinc-800 p-5 transition-all hover:bg-zinc-700/50"
                >
                  <h2 className="text-base font-semibold text-white transition-colors group-hover:text-primary">
                    {persona.role}
                  </h2>
                  <p className="flex-1 text-sm leading-relaxed text-zinc-400">
                    {persona.metaDescription}
                  </p>
                  <span className="mt-1 flex items-center gap-1 text-xs text-zinc-500 transition-colors group-hover:text-zinc-300">
                    Read more
                    <CircleArrowRight02Icon width={14} height={14} />
                  </span>
                </Link>
              ))}
            </div>
          </section>
        )}
      </div>
      <FinalSection />
    </>
  );
}
