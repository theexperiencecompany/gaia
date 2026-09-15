// @vitest-environment jsdom
/**
 * Two quick clicks on the collapse control send two requests, and the server's
 * replies are not guaranteed to come back in the order they were sent. The
 * checklist has to end on what the user last asked for, not on whichever
 * response happened to land last.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const fetchFirstSteps = vi.fn();
const setCollapsed = vi.fn();

vi.mock("@/features/first-steps/api/firstStepsApi", () => ({
  firstStepsApi: {
    fetch: () => fetchFirstSteps(),
    setCollapsed: (collapsed: boolean) => setCollapsed(collapsed),
  },
}));

vi.mock("next/navigation", () => ({ usePathname: () => "/c" }));

vi.mock("@/lib/toast", () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

import { useFirstSteps } from "@/features/first-steps/hooks/useFirstSteps";
import type { FirstStepsResponse } from "@/types/features/firstStepsTypes";

const checklist = (collapsed: boolean): FirstStepsResponse => ({
  collapsed,
  steps: [
    { key: "say_hi", done: true },
    { key: "connect_integration", done: false },
    { key: "link_platform", done: false },
    { key: "create_workflow", done: false },
  ],
});

interface Deferred {
  resolve: (value: FirstStepsResponse) => void;
  promise: Promise<FirstStepsResponse>;
}

const deferred = (): Deferred => {
  const { promise, resolve } = Promise.withResolvers<FirstStepsResponse>();
  return { resolve, promise };
};

describe("useFirstSteps collapse", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    vi.clearAllMocks();
    fetchFirstSteps.mockResolvedValue(checklist(false));
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
  });

  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );

  it("ends on the last click when the replies come back out of order", async () => {
    const first = deferred();
    const second = deferred();
    setCollapsed
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);
    const { result } = renderHook(() => useFirstSteps(), { wrapper });
    await waitFor(() => expect(result.current.totalCount).toBe(4));

    await act(async () => result.current.toggleCollapsed()); // collapse
    await waitFor(() => expect(result.current.collapsed).toBe(true));
    await act(async () => result.current.toggleCollapsed()); // expand again
    await waitFor(() => expect(result.current.collapsed).toBe(false));
    expect(setCollapsed.mock.calls).toEqual([[true], [false]]);

    // The expand's reply lands first, then the stale collapse's reply.
    await act(async () => second.resolve(checklist(false)));
    await act(async () => first.resolve(checklist(true)));
    await waitFor(() => expect(queryClient.isMutating()).toBe(0));

    expect(result.current.collapsed).toBe(false);
  });
});
