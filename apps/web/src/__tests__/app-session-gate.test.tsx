// @vitest-environment jsdom
/**
 * Regression: an unpaid account mid-onboarding fired /conversations,
 * /notifications and /integrations from the shell behind the wizard, and each
 * 402 surfaced as a "Failed to fetch conversations" or paywall toast. On the
 * routes an unpaid account lives on, the paid session must not mount until the
 * plan is read and allows it; everywhere else a signed-in account gets it at once.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, renderHook, waitFor } from "@testing-library/react";
import type React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const getSubscriptionStatus = vi.fn();
const paidSessionHook = vi.fn();
const usePathname = vi.fn();

vi.mock("@/i18n/navigation", () => ({ usePathname: () => usePathname() }));

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

const neverAnswers = () =>
  new Promise(() => {
    // The plan read stays in flight.
  });

beforeEach(() => {
  vi.clearAllMocks();
  usePathname.mockReturnValue("/onboarding");
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
  it("fires no paid request on onboarding for an account that never paid", async () => {
    getSubscriptionStatus.mockResolvedValue(status("free", false));

    render(<ProvidersLayout>page</ProvidersLayout>, { wrapper });

    await waitFor(() => expect(getSubscriptionStatus).toHaveBeenCalled());
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(paidSessionHook).not.toHaveBeenCalled();
  });

  it("fires no paid request on onboarding while the plan is unread", async () => {
    getSubscriptionStatus.mockReturnValue(neverAnswers());

    render(<ProvidersLayout>page</ProvidersLayout>, { wrapper });

    await waitFor(() => expect(getSubscriptionStatus).toHaveBeenCalled());
    expect(paidSessionHook).not.toHaveBeenCalled();
  });

  it("mounts the app for a signed-in account without waiting for the plan", async () => {
    usePathname.mockReturnValue("/c");
    getSubscriptionStatus.mockReturnValue(neverAnswers());

    render(<ProvidersLayout>page</ProvidersLayout>, { wrapper });

    await waitFor(() =>
      expect(paidSessionHook).toHaveBeenCalledWith("notifications"),
    );
  });

  it("mounts nothing in the app for a visitor who is not signed in", async () => {
    usePathname.mockReturnValue("/c");
    queryClient.removeQueries({ queryKey: CURRENT_USER_QUERY_KEY });

    render(<ProvidersLayout>page</ProvidersLayout>, { wrapper });

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
