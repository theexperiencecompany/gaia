/** A use-case page reports missing only when the API says the workflow does not exist; a failure throws so ISR keeps the last good page. */
import { ApiError } from "@shared/api";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { getExploreWorkflowsServer, getPublicWorkflowServer } = vi.hoisted(
  () => ({
    getExploreWorkflowsServer: vi.fn(),
    getPublicWorkflowServer: vi.fn(),
  }),
);

vi.mock("@/app/[locale]/(landing)/use-cases/[slug]/client", () => ({
  default: () => null,
}));

vi.mock("@/features/workflows/lib/serverWorkflowsApi", () => ({
  getExploreWorkflowsServer,
  getPublicWorkflowServer,
  getAllCommunityWorkflowsServer: vi.fn(),
}));

import { generateMetadata } from "@/app/[locale]/(landing)/use-cases/[slug]/page";

const params = (slug: string) => ({ params: Promise.resolve({ slug }) });

beforeEach(() => {
  getExploreWorkflowsServer.mockReset().mockResolvedValue([]);
  getPublicWorkflowServer.mockReset();
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

  it("throws when the explore list cannot load", async () => {
    getExploreWorkflowsServer.mockRejectedValue(new ApiError("down", 503));

    await expect(generateMetadata(params("any-503"))).rejects.toThrow("down");
  });
});
