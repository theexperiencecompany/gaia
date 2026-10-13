// @vitest-environment jsdom
//
// Covers the two behaviours that used to live in the hand-rolled
// `notificationStore` and are now the query cache's job:
//
//  1. a websocket push must land in the very list the UI renders, and
//  2. a failed mark-as-read must roll the optimistic update back.
//
// Both are exercised through the real hooks against a real QueryClient —
// only the network, the websocket transport, toasts and Next's router are
// faked, because those are the boundaries, not the code under test.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import type React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const getNotifications = vi.fn();
const markAsRead = vi.fn();

vi.mock("@/services/api/notifications", () => ({
  NotificationsAPI: {
    getNotifications: (...args: unknown[]) => getNotifications(...args),
    markAsRead: (...args: unknown[]) => markAsRead(...args),
  },
}));

vi.mock("@/lib/toast", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
    warning: vi.fn(),
  },
}));

type Handler = (msg: unknown) => void;
const handlers = new Map<string, Set<Handler>>();

vi.mock("@/lib/websocket/WebSocketManager", () => ({
  wsManager: {
    isConnected: true,
    on: (event: string, handler: Handler) => {
      const set = handlers.get(event) ?? new Set<Handler>();
      set.add(handler);
      handlers.set(event, set);
    },
    off: (event: string, handler: Handler) => {
      handlers.get(event)?.delete(handler);
    },
    onError: vi.fn(),
    offError: vi.fn(),
  },
}));

vi.mock("@/features/auth/hooks/useCurrentUser", () => ({
  useCurrentUser: () => ({ email: "test@example.com" }),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => "/notifications",
}));

vi.mock("@/services/syncService", () => ({
  batchSyncConversations: vi.fn(),
}));

import { notificationKeys } from "@/features/notification/api/queryKeys";
import { useNotifications } from "@/features/notification/hooks/useNotifications";
import { useNotificationWebSocket } from "@/features/notification/hooks/useNotificationWebSocket";
import {
  NotificationStatus,
  type NotificationView,
} from "@/types/features/notificationTypes";

function makeNotification(
  id: string,
  status: NotificationStatus = NotificationStatus.DELIVERED,
): NotificationView {
  return {
    id,
    user_id: "user_1",
    source: "test",
    type: "info",
    status,
    channels: [],
    content: { title: `Notification ${id}`, body: "" },
    created_at: new Date().toISOString(),
  } as unknown as NotificationView;
}

function page(notifications: NotificationView[]) {
  return { notifications, total: notifications.length, limit: 100, offset: 0 };
}

function withProviders(ui: React.ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
  return queryClient;
}

let markAsReadFn: (id: string) => Promise<void>;

function Probe() {
  const { notifications, unreadCount, markAsRead: mark } = useNotifications({});
  useNotificationWebSocket();
  markAsReadFn = mark;
  return (
    <div>
      <span data-testid="ids">{notifications.map((n) => n.id).join(",")}</span>
      <span data-testid="statuses">
        {notifications.map((n) => `${n.id}:${n.status}`).join(",")}
      </span>
      <span data-testid="unread">{String(unreadCount)}</span>
    </div>
  );
}

function emit(event: string, message: unknown) {
  for (const handler of handlers.get(event) ?? []) handler(message);
}

describe("notification query cache", () => {
  beforeEach(() => {
    handlers.clear();
    getNotifications.mockReset();
    markAsRead.mockReset();
  });

  it("lands a websocket push in the list the UI renders", async () => {
    getNotifications.mockResolvedValue(page([makeNotification("a")]));

    withProviders(<Probe />);
    await waitFor(() => {
      expect(screen.getByTestId("ids").textContent).toBe("a");
    });

    act(() => {
      emit("notification.delivered", {
        type: "notification.delivered",
        notification: makeNotification("b"),
      });
    });

    await waitFor(() => {
      // Prepended, not appended — newest notification first.
      expect(screen.getByTestId("ids").textContent).toBe("b,a");
    });
    expect(screen.getByTestId("unread").textContent).toBe("2");

    // A repeat of the same push must not duplicate the row.
    act(() => {
      emit("notification.delivered", {
        type: "notification.delivered",
        notification: makeNotification("b"),
      });
    });
    expect(screen.getByTestId("ids").textContent).toBe("b,a");
  });

  it("rolls the optimistic mark-as-read back when the request fails", async () => {
    getNotifications
      .mockResolvedValueOnce(page([makeNotification("a")]))
      // The onSettled invalidation refetches; pin it in flight so what the UI
      // shows is the rollback itself and not a fresh server page.
      .mockReturnValue(
        new Promise(() => {
          // Intentionally never settles.
        }),
      );
    markAsRead.mockRejectedValue(new Error("boom"));

    const queryClient = withProviders(<Probe />);
    await waitFor(() => {
      expect(screen.getByTestId("statuses").textContent).toBe("a:delivered");
    });

    await act(async () => {
      await markAsReadFn("a");
    });

    expect(markAsRead).toHaveBeenCalledWith("a");
    // Asserted on the cache, not the DOM: the rendered text is a render behind
    // the rollback here, so a DOM assertion would pass even with no rollback at
    // all — i.e. it could not fail, which is not a test.
    const cached = queryClient.getQueryData<{
      notifications: NotificationView[];
    }>(notificationKeys.list({ limit: 100 }));
    expect(cached?.notifications.map((n) => `${n.id}:${n.status}`)).toEqual([
      "a:delivered",
    ]);
  });
});
