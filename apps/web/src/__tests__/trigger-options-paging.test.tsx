// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const request = vi.fn();

vi.mock("@/lib/api/client", () => ({
  apiauth: { request: (...args: unknown[]) => request(...args) },
}));
vi.mock("@/lib/toast", () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));
vi.mock("@/lib/analytics", () => ({
  ANALYTICS_EVENTS: { API_REQUEST_FAILED: "api:request_failed" },
  trackEvent: vi.fn(),
}));

import {
  TRIGGER_OPTIONS_PAGE_SIZE,
  useInfiniteTriggerOptions,
} from "@/features/workflows/triggers/hooks/useInfiniteTriggerOptions";

const repos = (count: number, page: number) =>
  Array.from({ length: count }, (_, i) => {
    const name = `owner/repo-${page}-${i}`;
    return { value: name, label: name };
  });

describe("useInfiniteTriggerOptions", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    vi.clearAllMocks();
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
  });

  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );

  it("sends page and search to /triggers/options and pages while pages are full", async () => {
    request
      .mockResolvedValueOnce({
        data: { options: repos(TRIGGER_OPTIONS_PAGE_SIZE, 1) },
      })
      .mockResolvedValueOnce({ data: { options: repos(3, 2) } });

    const { result } = renderHook(
      () =>
        useInfiniteTriggerOptions(
          "github",
          "github_commit_event",
          "repo",
          true,
          "repo",
        ),
      { wrapper },
    );

    await waitFor(() => expect(result.current.hasNextPage).toBe(true));
    expect(request).toHaveBeenCalledWith(
      expect.objectContaining({
        method: "GET",
        url: "/triggers/options",
        params: expect.objectContaining({
          integration_id: "github",
          trigger_slug: "github_commit_event",
          field_name: "repo",
          page: 1,
          search: "repo",
        }),
      }),
    );

    await act(async () => {
      await result.current.fetchNextPage();
    });

    await waitFor(() => expect(result.current.hasNextPage).toBe(false));
    expect(request).toHaveBeenLastCalledWith(
      expect.objectContaining({
        params: expect.objectContaining({ page: 2, search: "repo" }),
      }),
    );
    expect(result.current.data?.pages.flat()).toHaveLength(
      TRIGGER_OPTIONS_PAGE_SIZE + 3,
    );
  });
});
