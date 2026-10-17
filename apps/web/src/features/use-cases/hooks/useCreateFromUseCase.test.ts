// @vitest-environment jsdom
/** A signed-out visitor always reaches login, whether or not crediting the creator worked. */

import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Workflow } from "@/features/workflows/api/workflowApi";

const creditWorkflow = vi.fn<(id: string) => Promise<unknown>>();
const handleAuthLogin = vi.fn<(returnUrl?: string) => void>();

vi.mock("@/features/referrals/api/referralsApi", () => ({
  referralsApi: { creditWorkflow: (id: string) => creditWorkflow(id) },
}));
vi.mock("@/features/auth/hooks/handleAuthLogin", () => ({
  handleAuthLogin: (returnUrl?: string) => handleAuthLogin(returnUrl),
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

import { useCreateFromUseCase } from "./useCreateFromUseCase";

const COMMUNITY_WORKFLOW = { id: "wf_community" } as Workflow;

describe("useCreateFromUseCase, signed out", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(console, "error").mockImplementation(() => undefined);
  });

  it.each([
    ["succeeds", () => creditWorkflow.mockResolvedValue({})],
    ["is rejected", () => creditWorkflow.mockRejectedValue(new Error("429"))],
  ])(
    "credits the creator and still logs in when the credit %s",
    async (_, arrange) => {
      arrange();
      const { result } = renderHook(() =>
        useCreateFromUseCase(null, COMMUNITY_WORKFLOW),
      );

      act(() => result.current.handleCreateWorkflow());

      await waitFor(() =>
        expect(handleAuthLogin).toHaveBeenCalledWith(window.location.pathname),
      );
      expect(creditWorkflow).toHaveBeenCalledWith("wf_community");
    },
  );
});
