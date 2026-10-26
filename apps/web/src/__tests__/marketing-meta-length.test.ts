/** Every landing page's title and description fit a result snippet in every locale, so none is cut off or thin. */
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import type { Metadata } from "next";
import { createTranslator } from "next-intl";
import type * as NextIntlServer from "next-intl/server";
import { describe, expect, it, vi } from "vitest";

import { locales } from "@/i18n/config";

const request = vi.hoisted(() => ({ locale: "en" }));

/** The request context next-intl reads from inside generateMetadata, answered for the locale under test. */
vi.mock("next-intl/server", async (importOriginal) => ({
  ...(await importOriginal<typeof NextIntlServer>()),
  getLocale: async () => request.locale,
  setRequestLocale: (locale: string) => {
    request.locale = locale;
  },
  getTranslations: async (
    options?: string | { locale?: string; namespace?: string },
  ) => {
    const { locale = request.locale, namespace } =
      typeof options === "string" ? { namespace: options } : (options ?? {});
    return createTranslator({
      locale,
      messages: readJson(path.join(MESSAGES_DIR, `${locale}.json`)),
      namespace,
    });
  },
}));

const DATA_DIR = path.join(process.cwd(), "public", "data");
const MESSAGES_DIR = path.join(process.cwd(), "src", "messages");
const SNIPPET = path.join(process.cwd(), "src", "config", "seoSnippet.json");
const FAMILIES = [
  "comparisons",
  "alternatives",
  "combos",
  "glossary",
  "personas",
  "guides",
] as const;
/** The overlay directory a family's translations live in, where it differs from the family. */
const OVERLAY_DIR: Partial<Record<(typeof FAMILIES)[number], string>> = {
  combos: "integrations",
};
const TITLE_MAX = 60;
/** Pages built from live API data; integrationMeta and useCaseMeta tests pin their description templates. */
const API_BACKED = new Set(["marketplace/[slug]", "use-cases/[slug]"]);

type Meta = { metaTitle?: string; metaDescription?: string };
type Params = Record<string, string>;
type PageModule = {
  metadata?: Metadata;
  generateMetadata?: (props: { params: Promise<Params> }) => Promise<Metadata>;
  generateStaticParams?: () => Promise<Params[]> | Params[];
};

const PAGES = import.meta.glob<PageModule>(
  "../app/\\[locale\\]/\\(landing\\)/**/page.tsx",
);

function readJson<T>(file: string): T {
  return JSON.parse(readFileSync(file, "utf8")) as T;
}

const { min: DESCRIPTION_MIN, max: DESCRIPTION_MAX } = readJson<{
  descriptionLength: { min: number; max: number };
}>(SNIPPET).descriptionLength;

/** The copy as a visitor sees it: tokens rendered at their longest plausible width. */
function rendered(value: string): string {
  return value
    .replaceAll("{{CURRENT_YEAR}}", "2026")
    .replaceAll("{{PRO_MONTHLY_PRICE}}", "20");
}

/** Each slug's meta in one locale: the base file for en, the overlay entry otherwise. */
function metaFor(
  family: (typeof FAMILIES)[number],
  locale: string,
  slugs: readonly string[],
): [string, Meta | undefined][] {
  if (locale === "en") {
    return slugs.map((slug) => [
      slug,
      readJson<Meta>(path.join(DATA_DIR, family, `${slug}.json`)),
    ]);
  }
  const overlayFile = path.join(
    DATA_DIR,
    "i18n",
    OVERLAY_DIR[family] ?? family,
    `${locale}.json`,
  );
  const overlay = existsSync(overlayFile)
    ? readJson<Record<string, Meta>>(overlayFile)
    : {};
  return slugs.map((slug) => [slug, overlay[slug]]);
}

function titlesOverLimit(): string[] {
  return FAMILIES.flatMap((family) => {
    const slugs = readJson<string[]>(
      path.join(DATA_DIR, family, "_slugs.json"),
    );
    return locales.flatMap((locale) =>
      metaFor(family, locale, slugs).flatMap(([slug, meta]) => {
        const title = rendered(meta?.metaTitle ?? "");
        return title.length > TITLE_MAX
          ? [`${locale} ${family}/${slug} title ${title.length}`]
          : [];
      }),
    );
  });
}

/** The route a page module serves, relative to the landing group: "learn/[term]". */
function routeOf(modulePath: string): string {
  return path.dirname(modulePath.split("(landing)/")[1] ?? "") || "/";
}

function isIndexable(metadata: Metadata): boolean {
  const { robots } = metadata;
  return !(robots && typeof robots === "object" && robots.index === false);
}

/** Every indexable page's description as generateMetadata renders it, in every locale. */
async function descriptionsOutOfRange(): Promise<string[]> {
  const failures: string[] = [];
  for (const [modulePath, load] of Object.entries(PAGES)) {
    const route = routeOf(modulePath);
    if (API_BACKED.has(route)) continue;
    const page = await load();
    const paramSets = (await page.generateStaticParams?.()) ?? [{}];
    // A static metadata export reads the same in every locale.
    for (const locale of page.metadata ? ["en"] : locales) {
      for (const params of paramSets) {
        request.locale = locale;
        const metadata =
          page.metadata ??
          (await page.generateMetadata?.({
            params: Promise.resolve({ locale, ...params }),
          }));
        if (!metadata || !isIndexable(metadata)) continue;
        const length = String(metadata.description ?? "").length;
        if (length < DESCRIPTION_MIN || length > DESCRIPTION_MAX) {
          const slug = Object.values(params).join("/");
          failures.push(`${length} ${locale} ${route} ${slug}`.trim());
        }
      }
    }
  }
  return failures;
}

describe("landing page meta", () => {
  it(`keeps programmatic titles within ${TITLE_MAX} characters`, () => {
    expect(titlesOverLimit()).toEqual([]);
  });

  it(`renders every description within ${DESCRIPTION_MIN}–${DESCRIPTION_MAX} characters`, async () => {
    expect(await descriptionsOutOfRange()).toEqual([]);
  }, 120_000);
});
