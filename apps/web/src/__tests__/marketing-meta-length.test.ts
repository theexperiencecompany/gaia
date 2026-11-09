/** Every landing page's title and description fit a result snippet in every locale, are its own in each locale, and share the canonical's URL. */
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import type { Metadata } from "next";
import type * as NextIntlServer from "next-intl/server";
import { describe, expect, it, vi } from "vitest";

import { locales } from "@/i18n/config";
import { isTranslatedPath } from "@/i18n/translatedRoutes";
import { siteConfig } from "@/lib/seo";
import { intlRequest } from "./helpers/nextIntlServer";

/** The request context next-intl reads from inside generateMetadata, answered for the locale under test. */
vi.mock("next-intl/server", async (importOriginal) =>
  (await import("./helpers/nextIntlServer")).mockNextIntlServer(
    importOriginal<typeof NextIntlServer>,
  ),
);

const DATA_DIR = path.join(process.cwd(), "public", "data");
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
/** Pages built from live API data; integrationMeta and useCaseMeta tests pin their description templates. */
const API_BACKED = new Set([
  "marketplace/[slug]",
  "marketplace/page/[page]",
  "use-cases/[slug]",
]);

type Meta = { metaTitle?: string; metaDescription?: string };
type Params = Record<string, string>;
type PageModule = {
  metadata?: Metadata;
  generateMetadata?: (props: { params: Promise<Params> }) => Promise<Metadata>;
  generateStaticParams?: () => Promise<Params[]> | Params[];
};
type Range = { min: number; max: number };

const PAGES = import.meta.glob<PageModule>(
  "../app/\\[locale\\]/\\(landing\\)/**/page.tsx",
);

function readJson<T>(file: string): T {
  return JSON.parse(readFileSync(file, "utf8")) as T;
}

const SNIPPET_RANGES = readJson<{
  titleLength: Range;
  descriptionLength: Range;
}>(SNIPPET);

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
        return title.length > SNIPPET_RANGES.titleLength.max
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

/** The <title> a visitor sees: a plain string takes the locale layout's " | GAIA" template, an absolute one stands as-is. */
function renderedTitle(title: Metadata["title"]): string {
  if (typeof title === "string") return `${title} | ${siteConfig.short_name}`;
  if (title && typeof title === "object" && "absolute" in title) {
    return title.absolute;
  }
  return "";
}

function absoluteUrl(url: unknown): string | undefined {
  return url ? new URL(String(url), siteConfig.url).href : undefined;
}

interface RenderedPage {
  /** Route plus params, the same in every locale of one page: "for/[persona] agency-owners". */
  readonly page: string;
  readonly route: string;
  readonly locale: string;
  readonly title: string;
  readonly description: string;
  readonly canonical: string | undefined;
  readonly ogUrl: string | undefined;
}

/** Every indexable page's metadata as generateMetadata renders it, in every locale. */
async function renderAllPages(): Promise<RenderedPage[]> {
  const pages: RenderedPage[] = [];
  for (const [modulePath, load] of Object.entries(PAGES)) {
    const route = routeOf(modulePath);
    if (API_BACKED.has(route)) continue;
    const page = await load();
    const paramSets = (await page.generateStaticParams?.()) ?? [{}];
    // Untranslated routes redirect to English, and a static export reads the same in every locale.
    const servedIn =
      page.metadata || !isTranslatedPath(`/${route}`) ? ["en"] : locales;
    for (const locale of servedIn) {
      for (const params of paramSets) {
        intlRequest.locale = locale;
        const metadata =
          page.metadata ??
          (await page.generateMetadata?.({
            params: Promise.resolve({ locale, ...params }),
          }));
        if (!metadata || !isIndexable(metadata)) continue;
        pages.push({
          page: `${route} ${Object.values(params).join("/")}`.trim(),
          route,
          locale,
          title: renderedTitle(metadata.title),
          description: String(metadata.description ?? ""),
          canonical: absoluteUrl(metadata.alternates?.canonical),
          ogUrl: absoluteUrl(metadata.openGraph?.url),
        });
      }
    }
  }
  return pages;
}

let renderedPages: Promise<RenderedPage[]> | undefined;
function allPages(): Promise<RenderedPage[]> {
  renderedPages ??= renderAllPages();
  return renderedPages;
}

/** Full-width CJK and Hangul characters, each as wide in a result snippet as two Latin ones. */
const WIDE_CHARACTER = /[ᄀ-ᅟ⺀-꓏가-힣豈-﫿︰-﹏＀-｠￠-￦]/gu;

/** A short title is one that says too little; in CJK, half the characters say as much. */
function titleWidth(title: string): number {
  return title.length + (title.match(WIDE_CHARACTER)?.length ?? 0);
}

async function outOfRange(
  field: "title" | "description",
  { min, max }: Range,
): Promise<string[]> {
  const shortness = field === "title" ? titleWidth : (s: string) => s.length;
  return (await allPages()).flatMap(({ page, locale, [field]: value }) =>
    shortness(value) < min || value.length > max
      ? [`${value.length} ${locale} ${page}`]
      : [],
  );
}

/** Translated pages whose title or description reads the same in two locales: one page, served untranslated. */
async function sharedAcrossLocales(
  field: "title" | "description",
): Promise<string[]> {
  const localesByCopy = new Map<string, string[]>();
  for (const page of await allPages()) {
    if (!isTranslatedPath(`/${page.route}`)) continue;
    const key = JSON.stringify([page.page, page[field]]);
    localesByCopy.set(key, [...(localesByCopy.get(key) ?? []), page.locale]);
  }
  return [...localesByCopy].flatMap(([key, shared]) =>
    shared.length > 1 ? [`${JSON.parse(key)[0]}: ${shared.join(",")}`] : [],
  );
}

describe("landing page meta", () => {
  it(`keeps programmatic titles within ${SNIPPET_RANGES.titleLength.max} characters`, () => {
    expect(titlesOverLimit()).toEqual([]);
  });

  it("renders every title and description within the snippet ranges", async () => {
    expect(await outOfRange("title", SNIPPET_RANGES.titleLength)).toEqual([]);
    expect(
      await outOfRange("description", SNIPPET_RANGES.descriptionLength),
    ).toEqual([]);
  }, 120_000);

  it("gives every translated page its own title and description in each locale", async () => {
    expect(await sharedAcrossLocales("title")).toEqual([]);
    expect(await sharedAcrossLocales("description")).toEqual([]);
  }, 120_000);

  it("points og:url at the page's canonical", async () => {
    const mismatched = (await allPages()).flatMap(
      ({ page, locale, canonical, ogUrl }) =>
        canonical === ogUrl
          ? []
          : [`${locale} ${page}: ${ogUrl} != ${canonical}`],
    );
    expect(mismatched).toEqual([]);
  }, 120_000);
});
