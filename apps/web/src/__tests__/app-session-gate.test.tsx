// @vitest-environment jsdom
/**
 * Regression: an unpaid account mid-onboarding fired /conversations,
 * /notifications and /integrations from the shell behind the wizard, and each
 * 402 surfaced as a "Failed to fetch conversations" or paywall toast. The paid
 * session must not mount until the plan is read and allows it.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, renderHook, waitFor } from "@testing-library/react";
import type React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const getSubscriptionStatus = vi.fn();
const paidSessionHook = vi.fn();

vi.mock("@/features/auth/api/authApi", () => ({
  authApi: {
    fetchUserInfo: () =>
      new Promise(() => {
        // Intentionally never settles; the user is seeded into the cache.
      }),
  },
}));

vi.mock("@/features/pricing/api/pricingApi", () => ({
  pricingApi: {
    getSubscriptionStatus: (...args: unknown[]) =>
      getSubscriptionStatus(...args),
  },
}));

// Every paid-session hook ProvidersLayout mounts; each records that it ran.
vi.mock("@/lib/websocket/useWebSocketConnection", () => ({
  useWebSocketConnection: () => paidSessionHook("websocket"),
}));
vi.mock("@/features/notification/hooks/useNotifications", () => ({
  useNotifications: () => paidSessionHook("notifications"),
}));
vi.mock("@/features/notification/hooks/useNotificationWebSocket", () => ({
  useNotificationWebSocket: () => paidSessionHook("notification_ws"),
}));
vi.mock("@/features/chat/hooks/useBgMessageWebSocket", () => ({
  useBgMessageWebSocket: () => paidSessionHook("bg_messages"),
}));
vi.mock("@/features/chat/hooks/useExecutorStream", () => ({
  useExecutorStream: () => paidSessionHook("executor_stream"),
}));
vi.mock("@/features/chat/hooks/useExecutorCancelWebSocket", () => ({
  useExecutorCancelWebSocket: () => paidSessionHook("executor_cancel"),
}));
vi.mock("@/features/chat/hooks/useApprovalDecisionWebSocket", () => ({
  useApprovalDecisionWebSocket: () => paidSessionHook("approvals"),
}));
vi.mock("@/features/todo/hooks/useTodoWorkflowGlobalListener", () => ({
  useTodoWorkflowGlobalListener: () => paidSessionHook("todo_listener"),
}));
vi.mock("@/hooks/api/useAxiosInterceptor", () => ({ default: vi.fn() }));
vi.mock("@/hooks/providers/GlobalAuth", () => ({ default: () => null }));
vi.mock("@/hooks/providers/GlobalInterceptor", () => ({ default: () => null }));
vi.mock("@/components/ui/Toaster", () => ({ Toaster: () => null }));
vi.mock("@/components/electron/ElectronRouteGuard", () => ({
  ElectronRouteGuard: ({ children }: { children: React.ReactNode }) => children,
}));
vi.mock("@/components/providers/KeyboardShortcutsProvider", () => ({
  default: ({ children }: { children: React.ReactNode }) => children,
}));
vi.mock("next/dynamic", () => ({
  default: () => () => {
    paidSessionHook("integration_modal");
    return null;
  },
}));

import { CURRENT_USER_QUERY_KEY } from "@/features/auth/hooks/useCurrentUser";
import { useEntitlement } from "@/features/pricing/hooks/useEntitlement";
import ProvidersLayout from "@/layouts/ProvidersLayout";

let queryClient: QueryClient;

function wrapper({ children }: { children: React.ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

const status = (planType: "pro" | "free", hasEverSubscribed: boolean) => ({
  plan_type: planType,
  has_ever_subscribed: hasEverSubscribed,
});

beforeEach(() => {
  vi.clearAllMocks();
  queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  queryClient.setQueryData(CURRENT_USER_QUERY_KEY, {
    user_id: "6a2d7ca352a78634a790ac46",
    name: "Test",
    email: "test@example.com",
    picture: "",
  });
});

describe("useEntitlement", () => {
  it("is unknown until the plan is read", () => {
    getSubscriptionStatus.mockReturnValue(
      new Promise(() => {
        // Never answers.
      }),
    );

    const { result } = renderHook(() => useEntitlement(), { wrapper });

    expect(result.current).toBe("unknown");
  });

  it.each([
    [status("pro", true), "entitled"],
    [status("free", true), "lapsed"],
    [status("free", false), "never_subscribed"],
  ])("reads %o as %s", async (plan, expected) => {
    getSubscriptionStatus.mockResolvedValue(plan);

    const { result } = renderHook(() => useEntitlement(), { wrapper });

    await waitFor(() => expect(result.current).toBe(expected));
  });
});

describe("ProvidersLayout paid session", () => {
  it("fires no paid request for an account that never paid", async () => {
    getSubscriptionStatus.mockResolvedValue(status("free", false));

    render(<ProvidersLayout>page</ProvidersLayout>, { wrapper });

    await waitFor(() => expect(getSubscriptionStatus).toHaveBeenCalled());
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(paidSessionHook).not.toHaveBeenCalled();
  });

  it("mounts the paid session once the plan is Pro", async () => {
    getSubscriptionStatus.mockResolvedValue(status("pro", true));

    render(<ProvidersLayout>page</ProvidersLayout>, { wrapper });

    await waitFor(() =>
      expect(paidSessionHook).toHaveBeenCalledWith("notifications"),
    );
    expect(paidSessionHook).toHaveBeenCalledWith("websocket");
  });
});
