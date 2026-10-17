/** Every programmatic page's title and description fit a result snippet in every locale, so none is cut off. */
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { locales } from "@/i18n/config";

const DATA_DIR = path.join(process.cwd(), "public", "data");
const FAMILIES = [
  "comparisons",
  "alternatives",
  "combos",
  "glossary",
  "personas",
] as const;
const TITLE_MAX = 60;
const DESCRIPTION_MAX = 160;

type Meta = { metaTitle?: string; metaDescription?: string };

function readJson<T>(file: string): T {
  return JSON.parse(readFileSync(file, "utf8")) as T;
}

/** The copy as a visitor sees it: tokens rendered at their longest plausible width. */
function rendered(value: string): string {
  return value
    .replaceAll("{{CURRENT_YEAR}}", "2026")
    .replaceAll("{{PRO_MONTHLY_PRICE}}", "20");
}

/** Each slug's meta in one locale: the base file for en, the overlay entry otherwise. */
function metaFor(
  family: string,
  locale: string,
  slugs: readonly string[],
): [string, Meta | undefined][] {
  if (locale === "en") {
    return slugs.map((slug) => [
      slug,
      readJson<Meta>(path.join(DATA_DIR, family, `${slug}.json`)),
    ]);
  }
  const overlayFile = path.join(DATA_DIR, "i18n", family, `${locale}.json`);
  const overlay = existsSync(overlayFile)
    ? readJson<Record<string, Meta>>(overlayFile)
    : {};
  return slugs.map((slug) => [slug, overlay[slug]]);
}

function lengthFailures(label: string, meta: Meta): string[] {
  const title = rendered(meta.metaTitle ?? "");
  const description = rendered(meta.metaDescription ?? "");
  return [
    ...(title.length > TITLE_MAX ? [`${label} title ${title.length}`] : []),
    ...(description.length > DESCRIPTION_MAX
      ? [`${label} description ${description.length}`]
      : []),
  ];
}

function overLimit(): string[] {
  return FAMILIES.flatMap((family) => {
    const slugs = readJson<string[]>(
      path.join(DATA_DIR, family, "_slugs.json"),
    );
    return locales.flatMap((locale) =>
      metaFor(family, locale, slugs).flatMap(([slug, meta]) =>
        meta ? lengthFailures(`${locale} ${family}/${slug}`, meta) : [],
      ),
    );
  });
}

describe("programmatic page meta", () => {
  it(`keeps titles within ${TITLE_MAX} and descriptions within ${DESCRIPTION_MAX} characters`, () => {
    expect(overLimit()).toEqual([]);
  });
});
