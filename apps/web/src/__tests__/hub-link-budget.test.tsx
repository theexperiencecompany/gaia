/** No landing hub or group page renders more than 100 internal links counting the navbar and footer, and every child stays linked from a page of its hub. */

import { NextIntlClientProvider } from "next-intl";
import type * as NextIntlServer from "next-intl/server";
import { isValidElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import Footer from "@/components/navigation/Footer";
import { NavbarActions } from "@/components/navigation/NavbarActions";
import {
  NavbarItems,
  NavbarNavLinks,
} from "@/components/navigation/NavbarLinks";
import { LogoWithContextMenu } from "@/components/shared/LogoWithContextMenu";
import { getAllComparisonSlugs } from "@/features/comparisons/data/comparisonsData";
import { getAllGlossaryTermSlugs } from "@/features/glossary/data/glossaryData";
import { getAllComboSlugs } from "@/features/integrations/data/combosData";
import type { CommunityIntegration } from "@/features/integrations/types";
import { locales, stripLocalePrefix } from "@/i18n/config";
import { isTranslatedPath } from "@/i18n/translatedRoutes";
import { siteConfig } from "@/lib/seo";
import { intlRequest, readMessages } from "./helpers/nextIntlServer";

/** squirrelscan's links/internal-links ceiling. */
const MAX_INTERNAL_LINKS = 100;

/** Far more integrations than the marketplace lists today, so the directory is proven to page rather than to fit by luck. */
const MARKETPLACE = vi.hoisted(() => {
  const integration = (prefix: string, index: number) => ({
    integrationId: `${prefix}-${index}`,
    slug: `${prefix}-${index}`,
    name: `${prefix} ${String(index).padStart(3, "0")}`,
    description: "Integration",
    category: "productivity",
    iconUrl: null,
    cloneCount: 0,
    toolCount: 1,
    tools: [],
    publishedAt: null,
    creator: null,
  });
  const native = Array.from({ length: 40 }, (_, i) => integration("native", i));
  return {
    native,
    community: [
      ...Array.from({ length: 300 }, (_, i) => integration("community", i)),
      // A community MCP server named like a native integration, as Dropbox is.
      { ...integration("native-mcp", 0), name: native[0].name },
    ],
  };
});

vi.mock("next-intl/server", async (importOriginal) =>
  (await import("./helpers/nextIntlServer")).mockNextIntlServer(
    importOriginal<typeof NextIntlServer>,
  ),
);

vi.mock(
  "@/features/integrations/lib/serverMarketplaceApi",
  async (importOriginal) => ({
    ...(await importOriginal<object>()),
    getNativeIntegrations: async (): Promise<CommunityIntegration[]> =>
      MARKETPLACE.native,
    getAllCommunityIntegrations: async (): Promise<CommunityIntegration[]> =>
      MARKETPLACE.community,
  }),
);

/** The filterable grid reads useSearchParams, so the prerendered HTML holds its Suspense fallback: nothing. */
vi.mock("@/app/[locale]/(landing)/marketplace/client", () => ({
  IntegrationsPageClient: () => null,
}));

type Params = Record<string, string>;
interface HubPageModule {
  default: (props: {
    params: Promise<Params>;
  }) => ReactNode | Promise<ReactNode>;
  generateStaticParams?: () => Params[] | Promise<Params[]>;
}

const FIRST_PAGES = import.meta.glob<HubPageModule>(
  "../app/\\[locale\\]/\\(landing\\)/*/page.tsx",
);
const GROUP_PAGES = import.meta.glob<HubPageModule>(
  "../app/\\[locale\\]/\\(landing\\)/*/*/\\[*\\]/page.tsx",
);

interface Hub {
  readonly path: string;
  /** The route, under the hub, of the pages holding each of its groups in full. */
  readonly groupRoute?: string;
  /** Every page the hub owns linking to; absent for hubs that only curate. */
  readonly children?: () => Promise<string[]>;
  /** How many distinct group pages must link each child. */
  readonly minGroupLinks?: number;
}

const HUBS: readonly Hub[] = [
  {
    path: "/automate",
    groupRoute: "with/[app]",
    // A combo belongs to both its apps' pages.
    minGroupLinks: 2,
    children: async () =>
      (await getAllComboSlugs()).map((slug) => `/automate/${slug}`),
  },
  {
    path: "/compare",
    groupRoute: "category/[category]",
    minGroupLinks: 1,
    children: async () =>
      (await getAllComparisonSlugs()).map((slug) => `/compare/${slug}`),
  },
  {
    path: "/learn",
    groupRoute: "category/[category]",
    minGroupLinks: 1,
    children: async () =>
      (await getAllGlossaryTermSlugs()).map((slug) => `/learn/${slug}`),
  },
  {
    path: "/marketplace",
    groupRoute: "page/[page]",
    children: async () =>
      [...MARKETPLACE.native, ...MARKETPLACE.community].map(
        (integration) => `/marketplace/${integration.slug}`,
      ),
  },
  { path: "/alternative-to" },
  { path: "/best-ai-assistant" },
];

function moduleKey(hubPath: string, rest: string): string {
  return `../app/[locale]/(landing)${hubPath}/${rest}`;
}

/** Unwrap async server components at the root, which a static render cannot await itself. */
async function resolveAsyncRoot(node: ReactNode): Promise<ReactNode> {
  if (
    isValidElement<object>(node) &&
    typeof node.type === "function" &&
    node.type.constructor.name === "AsyncFunction"
  ) {
    const render = node.type as (props: object) => Promise<ReactNode>;
    return resolveAsyncRoot(await render(node.props));
  }
  return node;
}

function renderHtml(tree: ReactNode, locale: string): string {
  return renderToStaticMarkup(
    <NextIntlClientProvider locale={locale} messages={readMessages(locale)}>
      {tree}
    </NextIntlClientProvider>,
  );
}

/** Links to other pages of the site, repeats included; a same-page #fragment links no other page, and the audit skips it too. */
function internalHrefs(html: string): string[] {
  return [...html.matchAll(/<a\b[^>]*?\shref="([^"]+)"/g)]
    .map((match) => match[1])
    .filter(
      (href) =>
        (href.startsWith("/") && !href.startsWith("//")) ||
        href.startsWith(siteConfig.url),
    );
}

/** Each plain-text link's visible text with where it goes. */
function linkTexts(html: string): { text: string; href: string }[] {
  return [
    ...html.matchAll(/<a\b[^>]*?\shref="([^"]+)"[^>]*>([^<]*)<\/a>/g),
  ].map((match) => ({ href: match[1], text: match[2] }));
}

/** The landing layout's navbar and footer as they prerender for a signed-out visitor. */
function chromeLinkCount(locale: string): number {
  return internalHrefs(
    renderHtml(
      <>
        <LogoWithContextMenu />
        <NavbarNavLinks pathname="/" />
        <NavbarItems
          pathname="/"
          hoveredItem={null}
          onDropdownMouseEnter={() => undefined}
          onLinkMouseEnter={() => undefined}
        />
        <NavbarActions isAuthenticated={false} stars={0} isStarsLoading />
        <Footer />
      </>,
      locale,
    ),
  ).length;
}

interface RenderedHubPage {
  readonly label: string;
  readonly html: string;
  readonly hrefs: readonly string[];
  readonly isGroupPage: boolean;
}

async function renderHubPages(
  hub: Hub,
  locale: string,
): Promise<RenderedHubPage[]> {
  intlRequest.locale = locale;
  const renderPage = async (
    module: HubPageModule,
    params: Params,
    label: string,
    isGroupPage: boolean,
  ): Promise<RenderedHubPage> => {
    const html = renderHtml(
      await resolveAsyncRoot(
        await module.default({ params: Promise.resolve(params) }),
      ),
      locale,
    );
    return { label, html, hrefs: internalHrefs(html), isGroupPage };
  };
  const first = await FIRST_PAGES[moduleKey(hub.path, "page.tsx")]();
  const pages = [
    await renderPage(first, { locale }, `${locale} ${hub.path}`, false),
  ];
  if (!hub.groupRoute) return pages;
  const group =
    await GROUP_PAGES[moduleKey(hub.path, `${hub.groupRoute}/page.tsx`)]();
  for (const params of (await group.generateStaticParams?.()) ?? []) {
    pages.push(
      await renderPage(
        group,
        { locale, ...params },
        `${locale} ${hub.path}/${hub.groupRoute} ${Object.values(params).join("/")}`,
        true,
      ),
    );
  }
  return pages;
}

function localesOf(hub: Hub): readonly string[] {
  return isTranslatedPath(hub.path) ? locales : ["en"];
}

describe("hub link budget", () => {
  it(`renders at most ${MAX_INTERNAL_LINKS} internal links on every hub and group page, navbar and footer included`, async () => {
    const overBudget: string[] = [];
    for (const hub of HUBS) {
      for (const locale of localesOf(hub)) {
        const chrome = chromeLinkCount(locale);
        for (const page of await renderHubPages(hub, locale)) {
          const total = page.hrefs.length + chrome;
          if (total > MAX_INTERNAL_LINKS) {
            overBudget.push(`${page.label}: ${total}`);
          }
        }
      }
    }
    expect(overBudget).toEqual([]);
  }, 120_000);

  it("links every child from its hub's pages, and from enough of its group pages", async () => {
    const unlinked: string[] = [];
    for (const hub of HUBS) {
      if (!hub.children) continue;
      const children = await hub.children();
      for (const locale of localesOf(hub)) {
        const groupPagesLinking = new Map<string, Set<string>>();
        for (const page of await renderHubPages(hub, locale)) {
          for (const href of page.hrefs.map(stripLocalePrefix)) {
            const from = groupPagesLinking.get(href) ?? new Set<string>();
            if (page.isGroupPage) from.add(page.label);
            groupPagesLinking.set(href, from);
          }
        }
        const missing = children.filter((child) => {
          const from = groupPagesLinking.get(child);
          return !from || from.size < (hub.minGroupLinks ?? 0);
        });
        if (missing.length > 0) {
          unlinked.push(`${locale} ${hub.path}: ${missing.join(", ")}`);
        }
      }
    }
    expect(unlinked).toEqual([]);
  }, 120_000);

  it("never gives two marketplace directory links the same text for different pages", async () => {
    const hub = HUBS.find((candidate) => candidate.path === "/marketplace");
    if (!hub) throw new Error("the marketplace hub is missing from HUBS");
    const hrefsByText = new Map<string, Set<string>>();
    for (const page of await renderHubPages(hub, "en")) {
      for (const { text, href } of linkTexts(page.html)) {
        if (!href.startsWith("/marketplace/")) continue;
        hrefsByText.set(text, (hrefsByText.get(text) ?? new Set()).add(href));
      }
    }
    const ambiguous = [...hrefsByText]
      .filter(([, hrefs]) => hrefs.size > 1)
      .map(([text, hrefs]) => `${text}: ${[...hrefs].join(", ")}`);
    expect(ambiguous).toEqual([]);
  }, 120_000);
});
