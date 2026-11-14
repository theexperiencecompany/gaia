import { getTranslations, setRequestLocale } from "next-intl/server";
import { HubPagination } from "@/components/seo/HubPagination";
import JsonLd from "@/components/seo/JsonLd";
import { SiteLink } from "@/components/seo/SiteLink";
import { getAllTranslatedGlossaryTerms } from "@/features/glossary/data/getTranslatedGlossary";
import {
  glossaryCategoryGroups,
  glossaryCategoryPath,
} from "@/features/glossary/data/glossaryCategories";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import { hubPageCount, hubPageSlice } from "@/lib/hubPagination";
import {
  generateBreadcrumbSchema,
  generateItemListSchema,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";
import { GlossaryTermGrid } from "./GlossaryTermGrid";

interface LearnHubProps {
  readonly locale: string;
  readonly page: number;
}

export async function LearnHub({ locale, page }: LearnHubProps) {
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
    })),
  );

  // Page through the hub's usual category order so each page is a contiguous
  // chunk of the list it has always shown.
  const categories = glossaryCategoryGroups(allTerms, t);
  const orderedTerms = categories.flatMap((category) => category.items);

  // Only the current page's terms are serialized: the full list is paged so
  // neither the HTML nor the RSC flight payload carries every card.
  const totalPages = hubPageCount(orderedTerms.length);
  const currentPage = Math.min(Math.max(page, 1), totalPages);
  const pageTerms = hubPageSlice(orderedTerms, currentPage);

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

        {categories.map((category) => {
          const terms = pageTerms.filter(
            (term) => term.category === category.slug,
          );
          if (terms.length === 0) return null;

          return (
            <section key={category.slug} id={category.slug} className="mb-14">
              <div className="mb-6 flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2">
                <h2 className="text-2xl font-semibold text-white">
                  {category.label}
                </h2>
                <SiteLink
                  href={glossaryCategoryPath(category.slug)}
                  className="text-sm text-zinc-400 underline underline-offset-2 hover:text-zinc-200"
                >
                  {t("all_category_terms", {
                    count: category.items.length,
                    category: category.label,
                  })}
                </SiteLink>
              </div>
              <GlossaryTermGrid terms={terms} />
            </section>
          );
        })}

        <HubPagination
          pathname="/learn"
          page={currentPage}
          totalPages={totalPages}
        />
      </div>

      <FinalSection />
    </>
  );
}
