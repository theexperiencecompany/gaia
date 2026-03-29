import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";

import JsonLd from "@/components/seo/JsonLd";
import type { AlternativeData } from "@/features/alternatives/data/alternativesData";
import {
  getAllAlternatives,
  getAlternativesByCategory,
} from "@/features/alternatives/data/alternativesData";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import {
  generateBreadcrumbSchema,
  generateItemListSchema,
  generatePageMetadata,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";

export const metadata: Metadata = generatePageMetadata({
  title: "Best Alternatives to Popular Productivity Tools",
  description:
    "See how GAIA replaces Notion, ChatGPT, Todoist, Zapier, Superhuman, Obsidian, and 24 more tools. Honest fit scores and migration steps for each.",
  path: "/alternative-to",
  keywords: [
    "notion alternative",
    "chatgpt alternative",
    "todoist alternative",
    "zapier alternative",
    "superhuman alternative",
    "obsidian alternative",
    "ai productivity assistant",
    "best productivity tools 2026",
  ],
});

const CATEGORY_LABELS: Record<AlternativeData["category"], string> = {
  "productivity-suite": "Productivity Suites",
  "ai-assistant": "AI Assistants",
  calendar: "Calendar & Time Management",
  email: "Email",
  "task-manager": "Task Managers",
  automation: "Automation",
  notes: "Notes & Knowledge",
};

const CATEGORY_ORDER: AlternativeData["category"][] = [
  "ai-assistant",
  "productivity-suite",
  "task-manager",
  "email",
  "calendar",
  "automation",
  "notes",
];

function AlternativeCard({ alt }: { readonly alt: AlternativeData }) {
  return (
    <Link
      href={`/alternative-to/${alt.slug}`}
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
          className="relative flex h-8 w-8 items-center justify-center overflow-hidden rounded-md p-0"
          style={{ rotate: "9deg", zIndex: 0 }}
        >
          <Image
            src={`https://www.google.com/s2/favicons?domain=${alt.domain}&sz=128`}
            alt={alt.name}
            width={40}
            height={40}
            unoptimized
          />
        </div>
      </div>
      <h3 className="text-lg font-medium text-white transition-colors group-hover:text-primary">
        Best {alt.name} Alternative
      </h3>
      <p className="text-sm text-zinc-500">{alt.tagline}</p>
      <div className="mt-auto flex items-center gap-1.5 pt-2">
        {[0, 1, 2, 3, 4].map((i) => (
          <span
            key={`pip-${i}`}
            className={`inline-block h-2 w-2 rounded-full ${i < alt.gaiaFitScore ? "bg-emerald-400" : "bg-zinc-700"}`}
          />
        ))}
        <span className="ml-1 text-xs text-zinc-500">
          {alt.gaiaFitScore}/5 fit
        </span>
      </div>
    </Link>
  );
}

export default function AlternativesHubPage() {
  const allAlternatives = getAllAlternatives();

  const webPageSchema = generateWebPageSchema(
    "Best Alternatives to Popular Productivity Tools",
    "See how GAIA replaces Notion, ChatGPT, Todoist, Zapier, Superhuman, Obsidian, and more.",
    `${siteConfig.url}/alternative-to`,
    [
      { name: "Home", url: siteConfig.url },
      { name: "Alternatives", url: `${siteConfig.url}/alternative-to` },
    ],
  );

  const breadcrumbSchema = generateBreadcrumbSchema([
    { name: "Home", url: siteConfig.url },
    { name: "Alternatives", url: `${siteConfig.url}/alternative-to` },
  ]);

  const itemListSchema = generateItemListSchema(
    allAlternatives.map((a) => ({
      name: `Best ${a.name} Alternative`,
      url: `${siteConfig.url}/alternative-to/${a.slug}`,
      description: a.tagline,
    })),
    "Article",
  );

  return (
    <>
      <JsonLd data={[webPageSchema, breadcrumbSchema, itemListSchema]} />

      <div className="mx-auto max-w-5xl px-6 pt-36 pb-24">
        <header className="mb-16 text-center">
          <h1 className="mb-4 font-serif text-5xl font-normal text-white md:text-6xl">
            GAIA as Your Alternative
          </h1>
          <p className="mx-auto max-w-2xl text-xl text-zinc-400">
            Honest breakdowns of how GAIA replaces 30 popular productivity, AI,
            and automation tools — with fit scores and migration steps for each.
          </p>
        </header>

        <div className="space-y-16">
          {CATEGORY_ORDER.map((category) => {
            const items = getAlternativesByCategory(category);
            if (items.length === 0) return null;

            return (
              <section key={category}>
                <h2 className="mb-6 text-2xl font-semibold text-white">
                  {CATEGORY_LABELS[category]}
                </h2>
                <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
                  {items.map((alt) => (
                    <AlternativeCard key={alt.slug} alt={alt} />
                  ))}
                </div>
              </section>
            );
          })}
        </div>

        <section className="mt-20 rounded-3xl bg-zinc-800 p-8 text-center">
          <h2 className="mb-3 text-2xl font-semibold text-white">
            Don't see your tool?
          </h2>
          <p className="mx-auto mb-6 max-w-lg text-zinc-400">
            GAIA connects to 50+ tools via MCP and supports custom integrations.
            Compare GAIA side-by-side with any tool you use today.
          </p>
          <Link
            href="/compare"
            className="inline-flex items-center gap-2 rounded-full bg-primary px-6 py-3 text-sm font-medium text-black transition-opacity hover:opacity-90"
          >
            View head-to-head comparisons
          </Link>
        </section>
      </div>

      <FinalSection />
    </>
  );
}
