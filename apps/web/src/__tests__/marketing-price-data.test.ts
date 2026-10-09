/**
 * The static marketing data quotes GAIA's own monthly price only through the
 * price token, in every locale, and the loader writes the advertised price in
 * before any page sees it.
 */
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import {
  ADVERTISED_PRO_MONTHLY_PRICE,
  PRO_MONTHLY_PRICE_TOKEN,
} from "@/features/pricing/advertisedPrice";
import { locales } from "@/i18n/config";
import { loadFeatureTranslations } from "@/i18n/loadFeatureTranslations";
import { getFeatureEntry, getFeatureSlugs } from "@/lib/feature-data";

import competitorPrices from "./fixtures/competitor-twenty-dollar-prices.json";

const DATA_DIR = path.join(process.cwd(), "public", "data");
const PRICED_FEATURES = ["alternatives", "comparisons", "personas"] as const;

/** A $20 written the way any of the seven locales writes it: "$20", "20 $", "US$ 20", "20ドル", "20달러". */
const TWENTY_DOLLARS =
  /(?:US\$|\$)\s?20(?!\d)(?![.,]\d)|(?<![\d.,$])20(?!\d)(?:[.,]00)?\s?(?:\$|USD|ドル|달러|dólares|dollars)/g;

type Json = string | number | boolean | null | Json[] | { [key: string]: Json };

function* strings(
  node: Json,
  at: (string | number)[] = [],
): Generator<[(string | number)[], string]> {
  if (typeof node === "string") yield [at, node];
  else if (Array.isArray(node))
    for (const [i, child] of node.entries()) yield* strings(child, [...at, i]);
  else if (node && typeof node === "object")
    for (const [key, child] of Object.entries(node))
      yield* strings(child, [...at, key]);
}

/** Every marketing data file that can quote a price, relative to public/data. */
function pricedDataFiles(): string[] {
  return PRICED_FEATURES.flatMap((feature) => [
    ...readdirSync(path.join(DATA_DIR, feature))
      .filter((name) => name !== "_slugs.json")
      .map((name) => `${feature}/${name}`),
    ...readdirSync(path.join(DATA_DIR, "i18n", feature)).map(
      (name) => `i18n/${feature}/${name}`,
    ),
  ]);
}

function readData(file: string): Json {
  return JSON.parse(readFileSync(path.join(DATA_DIR, file), "utf8"));
}

describe("marketing price data", () => {
  it("leaves a literal $20 only where it is a competitor's price", () => {
    const remaining = pricedDataFiles().flatMap((file) =>
      [...strings(readData(file))]
        .map(([at, text]) => ({
          file,
          path: at,
          competitor_prices: text.match(TWENTY_DOLLARS)?.length ?? 0,
        }))
        .filter((hit) => hit.competitor_prices > 0),
    );
    const byKey = (a: { file: string; path: (string | number)[] }) =>
      `${a.file}#${JSON.stringify(a.path)}`;

    expect(remaining.map(byKey).toSorted()).toEqual(
      competitorPrices.map(byKey).toSorted(),
    );
    expect(
      remaining.toSorted((a, b) => byKey(a).localeCompare(byKey(b))),
    ).toEqual(
      competitorPrices.toSorted((a, b) => byKey(a).localeCompare(byKey(b))),
    );
  });

  it("quotes GAIA's price through the token in every locale", () => {
    for (const feature of ["alternatives", "comparisons"] as const)
      for (const locale of locales) {
        const raw = readFileSync(
          path.join(DATA_DIR, "i18n", feature, `${locale}.json`),
          "utf8",
        );
        expect(raw, `${feature}/${locale}`).toContain(PRO_MONTHLY_PRICE_TOKEN);
      }
  });

  it.each(locales.filter((locale) => locale !== "en"))(
    "writes the advertised price into every %s translation",
    async (locale) => {
      for (const feature of PRICED_FEATURES) {
        const translated = JSON.stringify(
          await loadFeatureTranslations(locale, feature),
        );
        expect(translated).not.toContain(PRO_MONTHLY_PRICE_TOKEN);
        const raw = readFileSync(
          path.join(DATA_DIR, "i18n", feature, `${locale}.json`),
          "utf8",
        );
        const quoted = raw.split(PRO_MONTHLY_PRICE_TOKEN).length - 1;
        const advertised = String(ADVERTISED_PRO_MONTHLY_PRICE);
        expect(translated.split(advertised).length - 1).toBeGreaterThanOrEqual(
          quoted,
        );
      }
    },
  );

  it("writes the advertised price into every English entry", async () => {
    for (const feature of PRICED_FEATURES) {
      for (const slug of await getFeatureSlugs(feature)) {
        const entry = JSON.stringify(await getFeatureEntry(feature, slug));
        expect(entry, `${feature}/${slug}`).not.toContain(
          PRO_MONTHLY_PRICE_TOKEN,
        );
      }
    }
    const notion = JSON.stringify(
      await getFeatureEntry("alternatives", "notion"),
    );
    expect(notion).toContain(
      `Pro plans start at $${ADVERTISED_PRO_MONTHLY_PRICE}/month.`,
    );
  });
});
