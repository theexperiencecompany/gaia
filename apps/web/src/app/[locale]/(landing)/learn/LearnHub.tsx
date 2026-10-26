import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getTranslations, setRequestLocale } from "next-intl/server";
import { HubPagination, HubSectionNav } from "@/components/seo/HubPageNav";
import JsonLd from "@/components/seo/JsonLd";
import { SiteLink } from "@/components/seo/SiteLink";
import { getAllTranslatedGlossaryTerms } from "@/features/glossary/data/getTranslatedGlossary";
import { getAllGlossaryTerms } from "@/features/glossary/data/glossaryData";
import { glossaryHubPages } from "@/features/glossary/data/glossaryHubPages";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import { generateLocalizedPageMetadata } from "@/i18n/getAlternates";
import { hubPagePath } from "@/lib/hubPagination";
import {
  generateBreadcrumbSchema,
  generateItemListSchema,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";

const HUB_PATH = "/learn";

const HUB_KEYWORDS = [
  "AI glossary",
  "AI terminology",
  "productivity glossary",
  "AI concepts explained",
  "automation glossary",
  "AI agent definition",
  "LangGraph explained",
  "MCP explained",
  "workflow automation glossary",
];

export async function generateLearnHubMetadata(
  locale: string,
  page: number,
): Promise<Metadata> {
  const [t, terms] = await Promise.all([
    getTranslations({ locale, namespace: "glossary" }),
    getAllGlossaryTerms(),
  ]);
  const total = glossaryHubPages(terms, t).length;
  return generateLocalizedPageMetadata({
    title:
      page === 1
        ? t("hub_meta_title")
        : t("hub_page_meta_title", { page, total }),
    description:
      page === 1
        ? t("hub_meta_description")
        : t("hub_page_meta_description", { page, total }),
    path: hubPagePath(HUB_PATH, page),
    keywords: HUB_KEYWORDS,
    locale,
  });
}

/** One page of the /learn hub: its categories' terms, the jump links to them, and links to every other page. */
export async function LearnHubPage({
  locale,
  page,
}: {
  readonly locale: string;
  readonly page: number;
}) {
  setRequestLocale(locale);
  const [t, tCommon, allTerms] = await Promise.all([
    getTranslations({ locale, namespace: "glossary" }),
    getTranslations({ locale, namespace: "common" }),
    getAllTranslatedGlossaryTerms(locale),
  ]);
  const pages = glossaryHubPages(allTerms, t);
  const hubPage = pages.find((candidate) => candidate.page === page);
  if (!hubPage) notFound();

  const pageUrl = `${siteConfig.url}${hubPagePath(HUB_PATH, page)}`;
  const breadcrumbs = [
    { name: "Home", url: siteConfig.url },
    { name: t("breadcrumb"), url: `${siteConfig.url}${HUB_PATH}` },
    ...(page === 1
      ? []
      : [{ name: tCommon("page_label", { page }), url: pageUrl }]),
  ];

  const webPageSchema = generateWebPageSchema(
    t("hub_title"),
    t("hub_subtitle"),
    pageUrl,
    breadcrumbs,
  );
  const breadcrumbSchema = generateBreadcrumbSchema(breadcrumbs);
  const itemListSchema = generateItemListSchema(
    hubPage.sections.flatMap((section) =>
      section.items.map((term) => ({
        name: term.term,
        url: `${siteConfig.url}/learn/${term.slug}`,
      })),
    ),
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

        <HubSectionNav
          label={tCommon("section_nav_label")}
          sections={hubPage.sections}
        />

        {hubPage.sections.map((section) => (
          <section key={section.id} id={section.id} className="mb-14">
            <h2 className="mb-6 text-2xl font-semibold text-white">
              {section.label}
            </h2>

            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {section.items.map((term) => (
                <SiteLink
                  key={term.slug}
                  href={`/learn/${term.slug}`}
                  className="group flex flex-col gap-2 rounded-3xl bg-zinc-800 p-5 transition-colors hover:bg-zinc-700/50"
                >
                  <h3 className="mb-2 text-lg font-semibold text-white transition-colors group-hover:text-primary">
                    {term.term}
                  </h3>
                  <p className="line-clamp-3 text-sm leading-relaxed text-zinc-400">
                    {term.definition}
                  </p>
                </SiteLink>
              ))}
            </div>
          </section>
        ))}

        <HubPagination
          hubPath={HUB_PATH}
          current={page}
          total={pages.length}
          label={tCommon("pagination_label")}
          pageLabel={(n) => tCommon("page_label", { page: n })}
        />
      </div>

      <FinalSection />
    </>
  );
}
