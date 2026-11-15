// @vitest-environment jsdom
/** A signed-out visitor always reaches the instance's sign-in page, whatever crediting the creator does. */

import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Workflow } from "@/features/workflows/api/workflowApi";

const request = vi.fn();
const push = vi.fn<(href: string) => void>();

// Only the transport is stubbed, so the credit call keeps its real timeout.
vi.mock("@/lib/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof ApiClient>()),
  apiauth: { request: (...args: unknown[]) => request(...args) },
  apiOrigin: "http://localhost:8000",
}));
vi.mock("@/lib/toast", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));
vi.mock("@/lib/analytics", () => ({ track: vi.fn() }));
vi.mock("@/i18n/navigation", () => ({
  useRouter: () => ({ push }),
  usePathname: () => "/use-cases/inbox-zero",
}));
vi.mock("@/features/auth/hooks/useAuth", () => ({
  useAuth: () => ({ isAuthenticated: false }),
}));
vi.mock("@/features/workflows/hooks/useWorkflowCreation", () => ({
  useWorkflowCreation: () => ({ createWorkflow: vi.fn() }),
}));
vi.mock("@/features/chat/hooks/useWorkflowSelection", () => ({
  useWorkflowSelection: () => ({ selectWorkflow: vi.fn() }),
}));

import type * as ApiClient from "@/lib/api/client";
import { useCreateFromUseCase } from "./useCreateFromUseCase";

const COMMUNITY_WORKFLOW = { id: "wf_community" } as Workflow;
const LOGIN = "/login?return_url=%2Fuse-cases%2Finbox-zero";

/** A transport that answers only by failing once the request's signal aborts, as axios does. */
function neverAnswers(config: { signal?: AbortSignal }): Promise<never> {
  return new Promise((_, reject) => {
    config.signal?.addEventListener("abort", () =>
      reject(Object.assign(new Error("canceled"), { code: "ERR_CANCELED" })),
    );
  });
}

describe("useCreateFromUseCase, signed out", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(console, "error").mockImplementation(() => undefined);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it.each([
    [
      "succeeds",
      () => request.mockResolvedValue({ status: 200, data: {}, headers: {} }),
    ],
    [
      "is rejected",
      () => request.mockRejectedValue(new Error("Network Error")),
    ],
  ])(
    "credits the creator and still signs in through the login page when the credit %s",
    async (_, arrange) => {
      arrange();
      const { result } = renderHook(() =>
        useCreateFromUseCase(null, COMMUNITY_WORKFLOW),
      );

      act(() => result.current.handleCreateWorkflow());

      await waitFor(() => expect(push).toHaveBeenCalledWith(LOGIN));
      expect(request).toHaveBeenCalledWith(
        expect.objectContaining({
          url: "http://localhost:8000/api/v1/referrals/workflow-credit/wf_community",
        }),
      );
    },
  );

  it("stops waiting on a credit request that never answers and signs in", async () => {
    const timeout = new AbortController();
    const timeoutFor = vi
      .spyOn(AbortSignal, "timeout")
      .mockReturnValue(timeout.signal);
    request.mockImplementation(neverAnswers);
    const { result } = renderHook(() =>
      useCreateFromUseCase(null, COMMUNITY_WORKFLOW),
    );

    act(() => result.current.handleCreateWorkflow());
    await waitFor(() => expect(request).toHaveBeenCalledTimes(1));
    expect(push).not.toHaveBeenCalled();

    act(() => timeout.abort());

    await waitFor(() => expect(push).toHaveBeenCalledWith(LOGIN));
    expect(timeoutFor).toHaveBeenCalledWith(3_000);
  });
});
