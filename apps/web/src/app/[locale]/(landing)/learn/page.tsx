import type { Metadata } from "next";
import Link from "next/link";
import { getTranslations, setRequestLocale } from "next-intl/server";
import JsonLd from "@/components/seo/JsonLd";
import { getAllTranslatedGlossaryTerms } from "@/features/glossary/data/getTranslatedGlossary";
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
  const t = await getTranslations({ locale, namespace: "glossary" });

  const metadata = generatePageMetadata({
    title: t("hub_meta_title"),
    description: t("hub_meta_description"),
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

  return {
    ...metadata,
    alternates: {
      ...metadata.alternates,
      languages: getAlternates("/learn"),
    },
  };
}

const CATEGORY_KEYS: Record<string, string> = {
  "ai-concepts": "category_ai_concepts",
  productivity: "category_productivity",
  automation: "category_automation",
  email: "category_email",
  calendar: "category_calendar",
  "task-management": "category_task_management",
  "knowledge-management": "category_knowledge_management",
  development: "category_development",
};

const CATEGORY_ORDER = [
  "ai-concepts",
  "productivity",
  "automation",
  "email",
  "calendar",
  "task-management",
  "knowledge-management",
  "development",
];

export default async function LearnHubPage({ params }: PageProps) {
  const { locale } = await params;
  setRequestLocale(locale);
  const [t, allTerms] = await Promise.all([
    getTranslations({ locale, namespace: "glossary" }),
    getAllTranslatedGlossaryTerms(locale),
  ]);

  const webPageSchema = generateWebPageSchema(
    t("hub_title"),
    t("hub_subtitle"),
    `${siteConfig.url}/learn`,
    [
      { name: "Home", url: siteConfig.url },
      {
        name: t("breadcrumb"),
        url: `${siteConfig.url}/learn`,
      },
    ],
  );

  const breadcrumbSchema = generateBreadcrumbSchema([
    { name: "Home", url: siteConfig.url },
    { name: t("breadcrumb"), url: `${siteConfig.url}/learn` },
  ]);

  const itemListSchema = generateItemListSchema(
    allTerms.map((term) => ({
      name: term.term,
      url: `${siteConfig.url}/learn/${term.slug}`,
      description: term.definition,
    })),
    "Article",
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

        {CATEGORY_ORDER.map((categoryKey) => {
          const terms = allTerms.filter(
            (term) => term.category === categoryKey,
          );
          if (terms.length === 0) return null;

          return (
            <section key={categoryKey} className="mb-14">
              <h2 className="mb-6 text-2xl font-semibold text-white">
                {t(CATEGORY_KEYS[categoryKey] as Parameters<typeof t>[0])}
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
