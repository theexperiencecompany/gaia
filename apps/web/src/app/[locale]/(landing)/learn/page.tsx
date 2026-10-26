import type { Metadata } from "next";
import { getTranslations, setRequestLocale } from "next-intl/server";
import { HubGroupSection } from "@/components/seo/HubGroupSection";
import { HubIndex } from "@/components/seo/HubPageNav";
import JsonLd from "@/components/seo/JsonLd";
import { getAllTranslatedGlossaryTerms } from "@/features/glossary/data/getTranslatedGlossary";
import {
  glossaryCategoryGroups,
  glossaryCategoryPath,
} from "@/features/glossary/data/glossaryCategories";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import { generateLocalizedPageMetadata } from "@/i18n/getAlternates";
import {
  generateBreadcrumbSchema,
  generateItemListSchema,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";
import { GlossaryTermGrid } from "./GlossaryTermGrid";

/** Terms each category's section previews: two rows of three, the rest one click away on its category page. */
const TERMS_PER_CATEGORY = 6;

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

  return generateLocalizedPageMetadata({
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
    locale,
  });
}

export default async function LearnHubPage({ params }: PageProps) {
  const { locale } = await params;
  setRequestLocale(locale);
  const [t, tCommon, allTerms] = await Promise.all([
    getTranslations({ locale, namespace: "glossary" }),
    getTranslations({ locale, namespace: "common" }),
    getAllTranslatedGlossaryTerms(locale),
  ]);
  const categories = glossaryCategoryGroups(allTerms, t);

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
    categories.map((category) => ({
      name: category.label,
      url: `${siteConfig.url}${glossaryCategoryPath(category.slug)}`,
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

        <HubIndex
          label={tCommon("section_nav_label")}
          entries={categories.map((category) => ({
            id: `category-${category.slug}`,
            label: category.label,
            count: category.items.length,
          }))}
        />

        {categories.map((category) => (
          <HubGroupSection
            key={category.slug}
            id={`category-${category.slug}`}
            heading={category.label}
            headingClassName="text-2xl font-semibold text-white"
            allLink={{
              href: glossaryCategoryPath(category.slug),
              label: t("all_category_terms", {
                count: category.items.length,
                category: category.label,
              }),
            }}
          >
            <GlossaryTermGrid
              terms={category.items.slice(0, TERMS_PER_CATEGORY)}
            />
          </HubGroupSection>
        ))}
      </div>

      <FinalSection />
    </>
  );
}
