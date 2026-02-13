import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";

import JsonLd from "@/components/seo/JsonLd";
import { getAllComparisons } from "@/features/comparisons/data/comparisonsData";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import {
  generateBreadcrumbSchema,
  generateItemListSchema,
  generatePageMetadata,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";

export const metadata: Metadata = generatePageMetadata({
  title: "GAIA vs Competitors - AI Assistant Comparisons",
  description:
    "See how GAIA compares to ChatGPT, Gemini, Claude, Motion, n8n, Zapier, Reclaim, and more. Honest, detailed comparisons to help you choose the right AI productivity tool.",
  path: "/compare",
  keywords: [
    "GAIA comparisons",
    "AI assistant comparison",
    "ChatGPT alternative",
    "Zapier alternative",
    "n8n alternative",
    "Motion alternative",
    "AI productivity tools",
    "best AI assistant",
  ],
});

export default function ComparisonsHubPage() {
  const comparisons = getAllComparisons();

  const webPageSchema = generateWebPageSchema(
    "GAIA vs Competitors",
    "See how GAIA compares to other AI tools and productivity platforms.",
    `${siteConfig.url}/compare`,
    [
      { name: "Home", url: siteConfig.url },
      { name: "Comparisons", url: `${siteConfig.url}/compare` },
    ],
  );

  const breadcrumbSchema = generateBreadcrumbSchema([
    { name: "Home", url: siteConfig.url },
    { name: "Comparisons", url: `${siteConfig.url}/compare` },
  ]);

  const itemListSchema = generateItemListSchema(
    comparisons.map((c) => ({
      name: `GAIA vs ${c.name}`,
      url: `${siteConfig.url}/compare/${c.slug}`,
      description: c.description,
    })),
    "Article",
  );

  return (
    <>
      <JsonLd data={[webPageSchema, breadcrumbSchema, itemListSchema]} />

      <div className="mx-auto max-w-5xl px-6 pt-36 pb-24">
        <header className="mb-16 text-center">
          <h1 className="mb-4 font-serif text-5xl font-normal text-white md:text-6xl">
            How GAIA Compares
          </h1>
          <p className="mx-auto max-w-2xl text-xl text-zinc-400">
            Honest, detailed comparisons to help you choose the right AI
            productivity tool. See where GAIA excels and where others might fit
            better.
          </p>
        </header>

        <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
          {comparisons.map((comparison) => (
            <Link
              key={comparison.slug}
              href={`/compare/${comparison.slug}`}
              className="group flex flex-col gap-3 rounded-3xl bg-zinc-800 p-5 transition-all hover:bg-zinc-700/50"
            >
              <div className="flex items-center -space-x-2">
                <div
                  className="relative flex h-9 w-9 items-center justify-center p-0"
                  style={{ rotate: "-9deg", zIndex: 1 }}
                >
                  <Image
                    src="/images/logos/macos.webp"
                    alt="GAIA"
                    width={50}
                    height={50}
                  />
                </div>
                <div
                  className="relative flex h-8 w-8 items-center justify-center rounded-md overflow-hidden p-0"
                  style={{ rotate: "9deg", zIndex: 0 }}
                >
                  <Image
                    src={`https://www.google.com/s2/favicons?domain=${comparison.domain}&sz=128`}
                    alt={comparison.name}
                    width={40}
                    height={40}
                    unoptimized
                  />
                </div>
              </div>
              <h2 className="text-lg font-medium text-white transition-colors group-hover:text-primary">
                GAIA vs {comparison.name}
              </h2>
              <p className="text-sm text-zinc-500">{comparison.tagline}</p>
              <p className="line-clamp-2 text-sm leading-relaxed text-zinc-400">
                {comparison.description}
              </p>
            </Link>
          ))}
        </div>
      </div>

      <FinalSection />
    </>
  );
}
