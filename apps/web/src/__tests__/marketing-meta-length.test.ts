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

function overLimit(): string[] {
  const failures: string[] = [];
  for (const family of FAMILIES) {
    const slugs = readJson<string[]>(
      path.join(DATA_DIR, family, "_slugs.json"),
    );
    for (const locale of locales) {
      const overlayFile = path.join(DATA_DIR, "i18n", family, `${locale}.json`);
      const overlay =
        locale === "en" || !existsSync(overlayFile)
          ? {}
          : readJson<Record<string, Meta>>(overlayFile);
      for (const slug of slugs) {
        const meta =
          locale === "en"
            ? readJson<Meta>(path.join(DATA_DIR, family, `${slug}.json`))
            : overlay[slug];
        if (!meta) continue;
        const title = rendered(meta.metaTitle ?? "");
        const description = rendered(meta.metaDescription ?? "");
        if (title.length > TITLE_MAX) {
          failures.push(`${locale} ${family}/${slug} title ${title.length}`);
        }
        if (description.length > DESCRIPTION_MAX) {
          failures.push(
            `${locale} ${family}/${slug} description ${description.length}`,
          );
        }
      }
    }
  }
  return failures;
}

describe("programmatic page meta", () => {
  it(`keeps titles within ${TITLE_MAX} and descriptions within ${DESCRIPTION_MAX} characters`, () => {
    expect(overLimit()).toEqual([]);
  });
});
