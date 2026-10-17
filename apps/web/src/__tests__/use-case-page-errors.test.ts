/** A use-case page reports missing only on a real 404; a backend failure throws so ISR keeps the last good page. */
import { ApiError } from "@shared/api";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { getExploreWorkflows, getPublicWorkflow } = vi.hoisted(() => ({
  getExploreWorkflows: vi.fn(),
  getPublicWorkflow: vi.fn(),
}));

vi.mock("@/app/[locale]/(landing)/use-cases/[slug]/client", () => ({
  default: () => null,
}));

vi.mock("@/features/workflows/api/workflowApi", () => ({
  workflowApi: { getExploreWorkflows, getPublicWorkflow },
}));

import { generateMetadata } from "@/app/[locale]/(landing)/use-cases/[slug]/page";

const params = (slug: string) => ({ params: Promise.resolve({ slug }) });

beforeEach(() => {
  getExploreWorkflows.mockReset().mockResolvedValue({ workflows: [] });
  getPublicWorkflow.mockReset();
});

describe("use-case page resolution", () => {
  it("treats a 404 from the API as a missing use case", async () => {
    getPublicWorkflow.mockRejectedValue(new ApiError("not found", 404));

    await expect(generateMetadata(params("gone-404"))).resolves.toEqual({});
  });

  it("throws on a backend failure instead of rendering a not-found page", async () => {
    getPublicWorkflow.mockRejectedValue(new ApiError("boom", 500));

    await expect(generateMetadata(params("flaky-500"))).rejects.toThrow("boom");
  });

  it("throws when the explore list cannot load", async () => {
    getExploreWorkflows.mockRejectedValue(new ApiError("down", 503));

    await expect(generateMetadata(params("any-503"))).rejects.toThrow("down");
  });
});
