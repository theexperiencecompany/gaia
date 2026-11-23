// @vitest-environment jsdom
/** Endpoints that need a session are never asked for a signed-out visitor on a marketing page. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { listWorkflows, post } = vi.hoisted(() => ({
  listWorkflows: vi.fn(),
  post: vi.fn(),
}));

vi.mock("@/features/workflows/api/workflowApi", () => ({
  workflowApi: { listWorkflows: () => listWorkflows() },
}));

vi.mock("@/lib/api/typed", () => ({
  api: { post: (...args: unknown[]) => post(...args) },
}));

import { CURRENT_USER_QUERY_KEY } from "@/features/auth/hooks/useCurrentUser";
import { useUrlMetadata } from "@/features/chat/hooks/useUrlMetadata";
import { useWorkflows } from "@/features/workflows/hooks/useWorkflows";

const SIGNED_IN_USER = {
  user_id: "6812f0b3c9a14e2b7d5a91cc",
  email: "a@b.co",
  name: "A",
};
const LINK = "https://example.com/post";

function wrapperFor(signedIn: boolean) {
  const queryClient = new QueryClient();
  if (signedIn)
    queryClient.setQueryData(CURRENT_USER_QUERY_KEY, SIGNED_IN_USER);
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

const settle = () => new Promise((resolve) => setTimeout(resolve, 1200));

beforeEach(() => {
  vi.clearAllMocks();
  listWorkflows.mockResolvedValue({ workflows: [] });
  post.mockResolvedValue({ results: { [LINK]: { url: LINK } } });
});

describe("session-only queries", () => {
  it("lists no workflows for a signed-out visitor", async () => {
    renderHook(() => useWorkflows(), { wrapper: wrapperFor(false) });
    await settle();
    expect(listWorkflows).not.toHaveBeenCalled();
  });

  it("lists a signed-in user's workflows", async () => {
    renderHook(() => useWorkflows(), { wrapper: wrapperFor(true) });
    await waitFor(() => expect(listWorkflows).toHaveBeenCalledTimes(1));
  });

  it("asks no link preview for a signed-out visitor", async () => {
    renderHook(() => useUrlMetadata(LINK), { wrapper: wrapperFor(false) });
    await settle();
    expect(post).not.toHaveBeenCalled();
  });

  it("asks a signed-in user's link preview", async () => {
    renderHook(() => useUrlMetadata(LINK), { wrapper: wrapperFor(true) });
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1), {
      timeout: 3000,
    });
  });
});
