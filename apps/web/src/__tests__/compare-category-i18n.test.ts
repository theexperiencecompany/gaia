/** A translated /compare/category page names its category in the page's language, never the English key. */
import type * as NextIntlServer from "next-intl/server";
import { describe, expect, it, vi } from "vitest";

import ComparisonCategoryPage, {
  generateMetadata,
  generateStaticParams,
} from "@/app/[locale]/(landing)/compare/category/[category]/page";
import { CATEGORY_ORDER } from "@/features/comparisons/data/categories";
import { defaultLocale, locales } from "@/i18n/config";

vi.mock("next-intl/server", async (importOriginal) =>
  (await import("./helpers/nextIntlServer")).mockNextIntlServer(
    importOriginal<typeof NextIntlServer>,
  ),
);

const ENGLISH_LABELS = [...CATEGORY_ORDER, "Other"];
const translatedLocales = locales.filter((locale) => locale !== defaultLocale);

async function categorySlugs(): Promise<string[]> {
  const params = await generateStaticParams();
  return params.map((param) => param.category);
}

describe("comparison category labels", () => {
  it.each(translatedLocales)(
    "%s category page title, heading and meta carry no English category name",
    async (locale) => {
      for (const category of await categorySlugs()) {
        const params = Promise.resolve({ locale, category });
        const metadata = await generateMetadata({ params });
        const { props } = await ComparisonCategoryPage({ params });
        const rendered = [
          JSON.stringify(metadata.title),
          metadata.description,
          props.title,
          props.subtitle,
          props.categoryLabel,
        ].join(" ");
        for (const label of ENGLISH_LABELS) {
          expect(rendered, `${locale}/${category}`).not.toContain(label);
        }
      }
    },
  );

  it("renders the Spanish Other heading as Spanish", async () => {
    const params = Promise.resolve({ locale: "es", category: "other" });
    const metadata = await generateMetadata({ params });
    expect(JSON.stringify(metadata.title)).toContain("Otras categorías");
  });
});
