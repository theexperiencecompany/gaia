/** A community workflow that copies an official template canonicalizes to the template and stays out of the sitemap. */
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  getExploreWorkflowsServer,
  getPublicWorkflowServer,
  getAllCommunityWorkflowsServer,
} = vi.hoisted(() => ({
  getExploreWorkflowsServer: vi.fn(),
  getPublicWorkflowServer: vi.fn(),
  getAllCommunityWorkflowsServer: vi.fn(),
}));

vi.mock("@/app/[locale]/(landing)/use-cases/[slug]/client", () => ({
  default: () => null,
}));

vi.mock("@/features/workflows/lib/serverWorkflowsApi", () => ({
  getExploreWorkflowsServer,
  getPublicWorkflowServer,
  getAllCommunityWorkflowsServer,
}));

import { generateMetadata } from "@/app/[locale]/(landing)/use-cases/[slug]/page";
import { getSiteUrl } from "@/lib/seo";
import { getSitemapEntries, SITEMAP_IDS } from "@/lib/sitemapData";

const template = {
  id: "wf_template",
  slug: "auto-draft-replies",
  title: "Auto-Draft Replies",
  description: "Drafts replies for emails that need a response.",
  created_at: "2026-08-14T00:00:00Z",
};
const copy = {
  ...template,
  id: "wf_copy",
  slug: "auto-draft-replies-3c3bbe",
  title: "  auto-draft replies ",
  created_at: "2026-03-25T00:00:00Z",
};
const original = {
  ...template,
  id: "wf_own",
  slug: "hacker-news-digest",
  title: "Hacker News Digest",
  created_at: "2026-02-09T00:00:00Z",
};

beforeEach(() => {
  getExploreWorkflowsServer.mockReset().mockResolvedValue([template]);
  getAllCommunityWorkflowsServer
    .mockReset()
    .mockResolvedValue([copy, original]);
  getPublicWorkflowServer
    .mockReset()
    .mockImplementation(async (slug: string) =>
      [copy, original].find((w) => w.slug === slug),
    );
});

const params = (slug: string) => ({ params: Promise.resolve({ slug }) });

describe("community copies of an official template", () => {
  it("point their canonical at the template", async () => {
    const metadata = await generateMetadata(params(copy.slug));

    expect(metadata.alternates?.canonical).toBe(`/use-cases/${template.slug}`);
  });

  it("keep their own canonical when they are not a copy", async () => {
    const metadata = await generateMetadata(params(original.slug));

    expect(metadata.alternates?.canonical).toBe(`/use-cases/${original.slug}`);
  });

  it("are left out of the community sitemap", async () => {
    const entries = await getSitemapEntries(SITEMAP_IDS.COMMUNITY);

    expect(entries.map((e) => e.url)).toEqual([
      `${getSiteUrl()}/use-cases/${original.slug}`,
    ]);
  });
});
