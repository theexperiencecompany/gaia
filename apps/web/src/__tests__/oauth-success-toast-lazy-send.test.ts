// @vitest-environment jsdom
/**
 * Every landing page mounts useOAuthSuccessToast, so the chat send stack it
 * resumes the conversation with (dexie, zod, the chat stores) must load only on
 * an actual OAuth return, never as part of the hook's own import graph.
 */
import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const { sendModuleLoads } = vi.hoisted(() => ({
  sendModuleLoads: { count: 0 },
}));

let search = "";
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(search),
  useRouter: () => ({ replace: vi.fn() }),
  useParams: () => ({ id: "conv-1" }),
}));
vi.mock("@/i18n/navigation", () => ({ usePathname: () => "/c/conv-1" }));
vi.mock("@tanstack/react-query", () => ({
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}));
vi.mock("@/lib/toast", () => ({
  toast: { success: vi.fn(), info: vi.fn(), error: vi.fn() },
}));
vi.mock("@/features/chat/stream/sendMessage", () => {
  sendModuleLoads.count += 1;
  return { sendMessage: vi.fn() };
});

import { useOAuthSuccessToast } from "@/hooks/useOAuthSuccessToast";

describe("useOAuthSuccessToast chat send loading", () => {
  it("leaves the chat send stack unloaded on a page with no OAuth result", () => {
    search = "utm_source=newsletter";
    renderHook(() => useOAuthSuccessToast());

    expect(sendModuleLoads.count).toBe(0);
  });

  it("loads it once an OAuth success lands on a chat route", async () => {
    search = "oauth_success=true&integration=notion";
    window.history.replaceState(null, "", `/c/conv-1?${search}`);
    renderHook(() => useOAuthSuccessToast());

    await vi.waitFor(() => expect(sendModuleLoads.count).toBe(1));
  });
});
