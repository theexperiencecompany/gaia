import type { Metadata } from "next";
import Image from "next/image";
import { getTranslations, setRequestLocale } from "next-intl/server";
import JsonLd from "@/components/seo/JsonLd";
import { SiteLink } from "@/components/seo/SiteLink";
import type { AlternativeData } from "@/features/alternatives/data/alternativesData";
import { getTranslatedAlternatives } from "@/features/alternatives/data/getTranslatedAlternative";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import { generateLocalizedPageMetadata } from "@/i18n/getAlternates";
import {
  generateBreadcrumbSchema,
  generateItemListSchema,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";

interface PageProps {
  readonly params: Promise<{ readonly locale: string }>;
}

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "alternatives" });
  return generateLocalizedPageMetadata({
    title: t("hub_meta_title"),
    description: t("hub_meta_description"),
    path: "/alternative-to",
    keywords: [
      "notion alternative",
      "chatgpt alternative",
      "todoist alternative",
      "zapier alternative",
      "superhuman alternative",
      "obsidian alternative",
      "ai productivity assistant",
      `best productivity tools ${new Date().getFullYear()}`,
    ],
    locale,
  });
}

/** The alternatives message naming each category's section heading. */
const CATEGORY_LABEL_KEYS = {
  "productivity-suite": "category_productivity_suite",
  "ai-assistant": "category_ai_assistant",
  calendar: "category_calendar",
  email: "category_email",
  "task-manager": "category_task_manager",
  automation: "category_automation",
  notes: "category_notes",
} as const satisfies Record<AlternativeData["category"], string>;

const CATEGORY_ORDER: AlternativeData["category"][] = [
  "ai-assistant",
  "productivity-suite",
  "task-manager",
  "email",
  "calendar",
  "automation",
  "notes",
];

function AlternativeCard({
  alt,
  fitLabel,
}: {
  readonly alt: AlternativeData;
  readonly fitLabel: string;
}) {
  return (
    <SiteLink
      href={`/alternative-to/${alt.slug}`}
      className="group flex flex-col gap-3 rounded-3xl bg-zinc-800 p-5 transition-colors hover:bg-zinc-700/50"
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
        {alt.name}
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
          {alt.gaiaFitScore}/5 {fitLabel}
        </span>
      </div>
    </SiteLink>
  );
}

export default async function AlternativesHubPage({ params }: PageProps) {
  const { locale } = await params;
  setRequestLocale(locale);
  const [t, tCommon, allAlternatives] = await Promise.all([
    getTranslations({ locale, namespace: "alternatives" }),
    getTranslations({ locale, namespace: "common" }),
    getTranslatedAlternatives(locale),
  ]);
  // Pre-group by category since getAlternativesByCategory is now async — avoids
  // awaiting inside JSX render.
  const byCategory = new Map<string, typeof allAlternatives>();
  for (const alt of allAlternatives) {
    const list = byCategory.get(alt.category) ?? [];
    list.push(alt);
    byCategory.set(alt.category, list);
  }

  const webPageSchema = generateWebPageSchema(
    t("hub_meta_title"),
    t("hub_meta_description"),
    `${siteConfig.url}/alternative-to`,
    [
      { name: "Home", url: siteConfig.url },
      { name: t("breadcrumb"), url: `${siteConfig.url}/alternative-to` },
    ],
  );

  const breadcrumbSchema = generateBreadcrumbSchema([
    { name: "Home", url: siteConfig.url },
    { name: t("breadcrumb"), url: `${siteConfig.url}/alternative-to` },
  ]);

  const itemListSchema = generateItemListSchema(
    allAlternatives.map((a) => ({
      name: t("best_name_alternative", { name: a.name }),
      url: `${siteConfig.url}/alternative-to/${a.slug}`,
    })),
  );

  return (
    <>
      <JsonLd data={[webPageSchema, breadcrumbSchema, itemListSchema]} />

      <div className="mx-auto max-w-5xl px-6 pt-36 pb-24">
        <header className="mb-16 text-center">
          <h1 className="mb-4 font-serif text-5xl font-normal text-white md:text-6xl">
            {t("hub_title")}
          </h1>
          <p className="mx-auto max-w-2xl text-xl text-zinc-400">
            {t("hub_subtitle")}
          </p>
        </header>

        <div className="space-y-16">
          {CATEGORY_ORDER.map((category) => {
            const items = byCategory.get(category) ?? [];
            if (items.length === 0) return null;

            return (
              <section key={category}>
                <h2 className="mb-6 text-2xl font-semibold text-white">
                  {t(CATEGORY_LABEL_KEYS[category])}
                </h2>
                <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
                  {items.map((alt) => (
                    <AlternativeCard
                      key={alt.slug}
                      alt={alt}
                      fitLabel={t("fit_score")}
                    />
                  ))}
                </div>
              </section>
            );
          })}
        </div>

        <section className="mt-20 rounded-3xl bg-zinc-800 p-8 text-center">
          <h2 className="mb-3 text-2xl font-semibold text-white">
            {t("dont_see_your_tool")}
          </h2>
          <p className="mx-auto mb-6 max-w-lg text-zinc-400">
            {t("dont_see_your_tool_desc")}
          </p>
          <SiteLink
            href="/compare"
            className="inline-flex items-center gap-2 rounded-full bg-primary px-6 py-3 text-sm font-medium text-black transition-opacity hover:opacity-90"
          >
            {tCommon("view_comparisons")}
          </SiteLink>
        </section>
      </div>

      <FinalSection />
    </>
  );
}
