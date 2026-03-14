import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import { getTranslations, setRequestLocale } from "next-intl/server";

import JsonLd from "@/components/seo/JsonLd";
import {
  CATEGORY_ORDER,
  COMPARISON_CATEGORIES,
} from "@/features/comparisons/data/categories";
import { getTranslatedComparisons } from "@/features/comparisons/data/getTranslatedComparison";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import { getAlternates } from "@/i18n/getAlternates";
import {
  generateBreadcrumbSchema,
  generateItemListSchema,
  generatePageMetadata,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";

interface PageProps {
  readonly params: Promise<{
    readonly locale: string;
  }>;
}

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "comparisons" });

  const metadata = generatePageMetadata({
    title: t("hub_meta_title"),
    description: t("hub_meta_description"),
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

  return {
    ...metadata,
    alternates: {
      ...metadata.alternates,
      languages: getAlternates("/compare"),
    },
  };
}

export default async function ComparisonsHubPage({ params }: PageProps) {
  const { locale } = await params;
  setRequestLocale(locale);
  const [t, comparisons] = await Promise.all([
    getTranslations({ locale, namespace: "comparisons" }),
    getTranslatedComparisons(locale),
  ]);

  const webPageSchema = generateWebPageSchema(
    t("hub_title"),
    t("hub_subtitle"),
    `${siteConfig.url}/compare`,
    [
      { name: "Home", url: siteConfig.url },
      { name: t("breadcrumb"), url: `${siteConfig.url}/compare` },
    ],
  );

  const breadcrumbSchema = generateBreadcrumbSchema([
    { name: "Home", url: siteConfig.url },
    { name: t("breadcrumb"), url: `${siteConfig.url}/compare` },
  ]);

  const itemListSchema = generateItemListSchema(
    comparisons.map((c) => ({
      name: `${t("gaia_vs", { name: c.name })}`,
      url: `${siteConfig.url}/compare/${c.slug}`,
      description: c.description,
    })),
    "Article",
  );

  // Group comparisons by category
  const grouped: Record<string, typeof comparisons> = {};
  for (const comparison of comparisons) {
    const category = COMPARISON_CATEGORIES[comparison.slug] ?? "Other";
    if (!grouped[category]) {
      grouped[category] = [];
    }
    grouped[category].push(comparison);
  }

  const orderedCategories = [
    ...CATEGORY_ORDER.filter((cat) => grouped[cat]),
    ...(grouped["Other"] ? ["Other"] : []),
  ];

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

        {orderedCategories.map((category) => (
          <div key={category} className="mb-14">
            <h2 className="mb-6 border-b border-zinc-700 pb-3 text-xl font-semibold text-zinc-300">
              {category}
            </h2>
            <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
              {grouped[category].map((comparison) => (
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
                  <h3 className="text-lg font-medium text-white transition-colors group-hover:text-primary">
                    {t("gaia_vs", { name: comparison.name })}
                  </h3>
                  <p className="text-sm text-zinc-500">{comparison.tagline}</p>
                  <p className="line-clamp-2 text-sm leading-relaxed text-zinc-400">
                    {comparison.description}
                  </p>
                </Link>
              ))}
            </div>
          </div>
        ))}
      </div>

      <FinalSection />
    </>
  );
}
