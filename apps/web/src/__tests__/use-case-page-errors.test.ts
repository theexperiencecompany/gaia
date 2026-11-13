/** A use-case page reports missing only when the API says the workflow does not exist; a failure throws so ISR keeps the last good page. */
import { ApiError } from "@shared/api";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  getExploreWorkflowsServer,
  getPublicWorkflowServer,
  getCommunityWorkflowsServer,
} = vi.hoisted(() => ({
  getExploreWorkflowsServer: vi.fn(),
  getPublicWorkflowServer: vi.fn(),
  getCommunityWorkflowsServer: vi.fn(),
}));

vi.mock("@/app/[locale]/(landing)/use-cases/[slug]/client", () => ({
  default: () => null,
}));

vi.mock("@/features/workflows/lib/serverWorkflowsApi", () => ({
  getExploreWorkflowsServer,
  getPublicWorkflowServer,
  getCommunityWorkflowsServer,
  getAllCommunityWorkflowsServer: vi.fn(),
  COMMUNITY_PAGE_SIZE: 100,
}));

import UseCaseDetailPage, {
  generateMetadata,
} from "@/app/[locale]/(landing)/use-cases/[slug]/page";

const params = (slug: string) => ({ params: Promise.resolve({ slug }) });

beforeEach(() => {
  getExploreWorkflowsServer.mockReset().mockResolvedValue([]);
  getPublicWorkflowServer.mockReset();
  getCommunityWorkflowsServer
    .mockReset()
    .mockResolvedValue({ workflows: [], total: 0 });
});

describe("use-case page resolution", () => {
  it("treats a workflow the API does not have as a missing use case", async () => {
    getPublicWorkflowServer.mockResolvedValue(null);

    await expect(generateMetadata(params("gone-404"))).resolves.toEqual({});
  });

  it("throws on a backend failure instead of rendering a not-found page", async () => {
    getPublicWorkflowServer.mockRejectedValue(new ApiError("boom", 500));

    await expect(generateMetadata(params("flaky-500"))).rejects.toThrow("boom");
  });

  // The app links every workflow card to /use-cases/<slug> (integration
  // sidebar, use-case grid, workflow pages); each source's slug must render.
  it("renders the page for a curated workflow linked by its slug", async () => {
    getExploreWorkflowsServer.mockResolvedValue([
      { id: "wf_1", slug: "inbox-triage", title: "Inbox Triage", steps: [] },
    ]);

    const page = await UseCaseDetailPage(params("inbox-triage"));

    expect(JSON.stringify(page)).toContain('"slug":"inbox-triage"');
    expect(getPublicWorkflowServer).not.toHaveBeenCalled();
  });

  it("renders the page for a community workflow linked by its slug", async () => {
    getPublicWorkflowServer.mockResolvedValue({
      id: "wf_2",
      slug: "calendar-to-discord",
      title: "Calendar to Discord",
      steps: [],
    });

    const page = await UseCaseDetailPage(params("calendar-to-discord"));

    expect(JSON.stringify(page)).toContain('"slug":"calendar-to-discord"');
  });

  it("throws when the explore list cannot load", async () => {
    getExploreWorkflowsServer.mockRejectedValue(new ApiError("down", 503));

    await expect(generateMetadata(params("any-503"))).rejects.toThrow("down");
  });
});
