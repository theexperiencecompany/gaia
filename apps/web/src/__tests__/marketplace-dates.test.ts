/** A marketplace page tells the sitemap and its own WebPage schema the same modification date, and declares no Person for a creator without a profile. */
import type * as NextIntlServer from "next-intl/server";
import type { ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import IntegrationPage from "@/app/[locale]/(landing)/marketplace/[slug]/page";
import type { PublicIntegrationResponse } from "@/features/integrations/types";
import { getSitemapEntries, SITEMAP_IDS } from "@/lib/sitemapData";

// The marketplace is English-only; the page reads the request locale for its alternative guide.
vi.mock("next-intl/server", async (importOriginal) => ({
  ...(await importOriginal<typeof NextIntlServer>()),
  getLocale: async () => "en",
}));

const SLUG = "arxiv-mcp-education";

/** Trimmed from the production /integrations/public/{slug} record. */
const ARXIV: PublicIntegrationResponse = {
  integrationId: "int_arxiv",
  slug: SLUG,
  name: "arXiv",
  description: "Search and read arXiv papers.",
  category: "education",
  source: "custom",
  toolCount: 0,
  tools: [],
  publishedAt: "2026-01-13T20:29:25.088Z",
  creator: { name: "Vinit Thakkar", picture: null },
};

/** Answer each backend endpoint the page and sitemap call the way the backend does. */
function stubBackend(): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: Request) => {
      const { pathname } = new URL(input.url);
      if (pathname.endsWith(`/integrations/public/${SLUG}`)) {
        return Response.json(ARXIV);
      }
      if (pathname.endsWith("/workflows")) {
        return Response.json({ workflows: [], total: 0 });
      }
      if (pathname.endsWith("/integrations/config")) {
        return Response.json({ integrations: [] });
      }
      if (pathname.endsWith("/integrations/community")) {
        return Response.json({
          integrations: [{ ...ARXIV, cloneCount: 0, iconUrl: null }],
          total: 1,
          has_more: false,
        });
      }
      return new Response("not stubbed", { status: 404 });
    }),
  );
}

type PageElement = ReactElement<{
  children: ReactElement<{ data: Record<string, unknown>[] }>[];
}>;

async function pageSchemas(): Promise<Record<string, unknown>[]> {
  const page = (await IntegrationPage({
    params: Promise.resolve({ slug: SLUG }),
  })) as PageElement;
  const [jsonLd] = page.props.children;
  return jsonLd.props.data;
}

beforeEach(() => {
  vi.stubEnv("API_BASE_URL_INTERNAL", "http://api.test/api/v1");
  stubBackend();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("marketplace page dates", () => {
  it("lists the page in the sitemap at its WebPage dateModified", async () => {
    const entry = (await getSitemapEntries(SITEMAP_IDS.INTEGRATIONS)).find(
      ({ url }) => url === `https://heygaia.io/marketplace/${SLUG}`,
    );
    const webPage = (await pageSchemas()).find(
      (schema) => schema["@type"] === "WebPage",
    );

    expect(entry?.lastModified).toBeDefined();
    expect(webPage?.dateModified).toBeDefined();
    expect(new Date(entry?.lastModified as Date).toISOString()).toBe(
      new Date(String(webPage?.dateModified)).toISOString(),
    );
  });

  it("declares the integration as its own entity, with no Person for a creator who has no profile", async () => {
    const app = (await pageSchemas()).find(
      (schema) => schema["@type"] === "SoftwareApplication",
    );
    expect(app?.["@id"]).toBe(
      `https://heygaia.io/marketplace/${SLUG}#integration`,
    );
    expect(app?.author).toBeUndefined();
  });

  it("renders a native integration's page without asking for the community catalog", async () => {
    const GMAIL: PublicIntegrationResponse = {
      ...ARXIV,
      integrationId: "gmail",
      slug: "gmail",
      name: "Gmail",
      source: "platform",
    };
    const requested: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: Request) => {
        const { pathname } = new URL(input.url);
        requested.push(pathname);
        if (pathname.endsWith("/integrations/public/gmail")) {
          return Response.json(GMAIL);
        }
        if (pathname.endsWith("/workflows")) {
          return Response.json({ workflows: [], total: 0 });
        }
        if (pathname.endsWith("/integrations/config")) {
          return Response.json({ integrations: [] });
        }
        return new Response("not stubbed", { status: 500 });
      }),
    );

    const page = await IntegrationPage({
      params: Promise.resolve({ slug: "gmail" }),
    });

    expect(page).toBeTruthy();
    expect(
      requested.some((path) => path.endsWith("/integrations/community")),
    ).toBe(false);
  });
});
