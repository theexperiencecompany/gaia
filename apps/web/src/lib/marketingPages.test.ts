import { describe, expect, it, vi } from "vitest";

import { GET as getFeed } from "@/app/feed.xml/route";
import { GET as getLlms } from "@/app/llms.txt/route";
import { MARKETING_PAGES } from "@/lib/marketingPages";
import { siteConfig } from "@/lib/seo";

vi.mock("@/features/workflows/lib/serverWorkflowsApi", () => ({
  getExploreWorkflowsServer: async () => [],
  getAllCommunityWorkflowsServer: async () => [],
}));
vi.mock("@/features/integrations/lib/serverMarketplaceApi", () => ({
  getAllCommunityIntegrations: async () => [],
}));

describe("MARKETING_PAGES", () => {
  it("lists each page path once", () => {
    const paths = MARKETING_PAGES.map((page) => page.path);
    expect(new Set(paths).size).toBe(paths.length);
  });

  it("never claims a mobile app or a free hosted plan", () => {
    for (const page of MARKETING_PAGES) {
      expect(page.description).not.toMatch(
        /mobile|iOS|Android|free (tier|plan)/i,
      );
    }
  });

  it("is the Main pages section of /llms.txt, entry for entry", async () => {
    const body = await (await getLlms()).text();
    const section = body.split("## Main pages\n\n")[1].split("\n\n")[0];
    const lines = section.split("\n");

    expect(lines).toHaveLength(MARKETING_PAGES.length);
    for (const page of MARKETING_PAGES) {
      expect(lines).toContain(
        `- [${page.title}](${siteConfig.url}${page.path}): ${page.description}`,
      );
    }
  });

  it("is the static-page item set of /feed.xml", async () => {
    const body = await (await getFeed()).text();

    for (const page of MARKETING_PAGES) {
      const link = `${siteConfig.url}${page.path}`;
      expect(body).toContain(
        `<title><![CDATA[${page.title}]]></title>\n      <link>${link}</link>`,
      );
      expect(body).toContain(
        `<description><![CDATA[${page.description}]]></description>`,
      );
    }
  });
});
