// @vitest-environment node
import { PHASE_PRODUCTION_BUILD } from "next/constants";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { locales } from "@/i18n/config";
import {
  getAllCommunityIntegrations,
  getIntegrationWorkflows,
  getMarketplacePath,
  getNativeIntegrations,
  getPublicIntegration,
} from "./serverMarketplaceApi";

const SLUGS = ["gmail", "slack", "notion", "github", "linear"];

const NATIVE_CONFIG = {
  integrations: SLUGS.map((slug, index) => ({
    id: slug,
    slug,
    name: slug,
    description: "",
    category: "productivity",
    source: "platform",
    available: true,
    displayPriority: index,
  })),
};

function publicIntegration(slug: string) {
  return { integrationId: slug, slug, name: slug, category: "productivity" };
}

/** Answer the marketplace endpoints the way the backend does; a slug in failing gets a 500 once. */
function stubBackend(failing: Set<string> = new Set()) {
  const fetchMock = vi.fn(async (input: Request) => {
    const { pathname } = new URL(input.url);
    if (pathname.endsWith("/integrations/config")) {
      return Response.json(NATIVE_CONFIG);
    }
    if (pathname.endsWith("/integrations/community")) {
      return Response.json({ integrations: [], total: 0, has_more: false });
    }
    const workflows = pathname.match(/\/public\/([^/]+)\/workflows$/);
    if (workflows) return Response.json({ workflows: [] });
    const slug = pathname.split("/").at(-1) ?? "";
    if (failing.delete(slug)) return new Response("boom", { status: 500 });
    return Response.json(publicIntegration(slug));
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function requestedPaths(fetchMock: ReturnType<typeof stubBackend>): string[] {
  return fetchMock.mock.calls.map(([input]) => new URL(input.url).pathname);
}

/** Every read one marketplace detail page makes, as the build prerenders it for one locale. */
async function prerenderDetailPage(slug: string): Promise<void> {
  await Promise.all([getNativeIntegrations(), getAllCommunityIntegrations()]);
  await getPublicIntegration(slug);
  await getMarketplacePath(slug);
  await getIntegrationWorkflows(slug, 4);
}

beforeEach(() => {
  vi.stubEnv("API_BASE_URL_INTERNAL", "http://api.test/api/v1");
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("marketplace reads during the build", () => {
  it("reads the catalog once and each integration once, whatever the number of locales", async () => {
    vi.stubEnv("NEXT_PHASE", PHASE_PRODUCTION_BUILD);
    const fetchMock = stubBackend();

    await Promise.all(
      locales.flatMap(() => SLUGS.map((slug) => prerenderDetailPage(slug))),
    );

    const paths = requestedPaths(fetchMock);
    expect(
      paths.filter((path) => path.endsWith("/integrations/config")),
    ).toHaveLength(1);
    expect(
      paths.filter((path) => path.endsWith("/integrations/community")),
    ).toHaveLength(1);
    for (const slug of SLUGS) {
      expect(
        paths.filter((path) => path.endsWith(`/public/${slug}`)),
      ).toHaveLength(1);
      expect(
        paths.filter((path) => path.endsWith(`/public/${slug}/workflows`)),
      ).toHaveLength(1);
    }
    expect(paths).toHaveLength(2 + SLUGS.length * 2);
  });

  it("fails the page on a failed read, then reads again for the next page instead of reusing the failure", async () => {
    vi.stubEnv("NEXT_PHASE", PHASE_PRODUCTION_BUILD);
    const fetchMock = stubBackend(new Set(["asana"]));

    await expect(getPublicIntegration("asana")).rejects.toThrow(/500/);
    await expect(getPublicIntegration("asana")).resolves.toMatchObject({
      slug: "asana",
    });
    expect(
      requestedPaths(fetchMock).filter((path) => path.endsWith("/asana")),
    ).toHaveLength(2);
  });

  it("does not share reads across a running server's requests", async () => {
    const fetchMock = stubBackend();

    await getPublicIntegration("trello");
    await getPublicIntegration("trello");

    expect(
      requestedPaths(fetchMock).filter((path) => path.endsWith("/trello")),
    ).toHaveLength(2);
  });
});
