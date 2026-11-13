// @vitest-environment jsdom
/**
 * The header badge counts what GAIA told the user since they last opened the Updates page, and a
 * message arriving over the socket refreshes it.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  render,
  renderHook,
  screen,
  waitFor,
} from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const unseen = vi.fn();
const handlers = new Map<string, (message: unknown) => void>();

vi.mock("@/features/updates/api/updatesApi", () => ({
  updatesApi: {
    list: vi.fn(),
    unseen: (...args: unknown[]) => unseen(...args),
  },
}));

vi.mock("@/lib/websocket/WebSocketManager", () => ({
  wsManager: {
    on: (type: string, handler: (message: unknown) => void) =>
      handlers.set(type, handler),
    off: (type: string) => handlers.delete(type),
  },
}));

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

vi.mock("@/components/layout/headers/SidebarHeaderButton", () => ({
  SidebarHeaderButton: ({
    children,
    "aria-label": label,
  }: {
    children: ReactNode;
    "aria-label": string;
  }) => (
    <button type="button" aria-label={label}>
      {children}
    </button>
  ),
}));

import { UpdatesButton } from "@/features/updates/components/UpdatesButton";
import { useMarkUpdatesSeen } from "@/features/updates/hooks/useMarkUpdatesSeen";
import { useUpdatesLiveRefresh } from "@/features/updates/hooks/useUpdatesLiveRefresh";
import { useUpdatesSeenStore } from "@/features/updates/stores/updatesSeenStore";

const SEEN = "2026-11-10T09:00:00.000Z";

function clientWrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { client, wrapper };
}

describe("the Updates badge", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    handlers.clear();
    localStorage.clear();
    useUpdatesSeenStore.setState({ lastSeenAt: SEEN });
  });

  it("counts what was told since the page was last opened", async () => {
    unseen.mockResolvedValue({ count: 3 });
    const { wrapper } = clientWrapper();

    render(<UpdatesButton />, { wrapper });

    expect(await screen.findByText("3")).toBeDefined();
    expect(unseen).toHaveBeenCalledWith(SEEN);
  });

  it("links to the Updates page", () => {
    unseen.mockResolvedValue({ count: 0 });
    const { wrapper } = clientWrapper();

    render(<UpdatesButton />, { wrapper });

    expect(
      screen
        .getByRole("button", { name: "Updates" })
        .closest("a")
        ?.getAttribute("href"),
    ).toBe("/updates");
  });

  it("starts counting from now on a first run, so an existing feed is not new", async () => {
    unseen.mockResolvedValue({ count: 0 });
    useUpdatesSeenStore.setState({ lastSeenAt: null });
    const { wrapper } = clientWrapper();

    render(<UpdatesButton />, { wrapper });

    await waitFor(() =>
      expect(useUpdatesSeenStore.getState().lastSeenAt).not.toBeNull(),
    );
  });

  it("asks again after the page is opened, from the moment it was", async () => {
    unseen.mockResolvedValue({ count: 2 });
    const { wrapper } = clientWrapper();
    render(<UpdatesButton />, { wrapper });
    await screen.findByText("2");
    unseen.mockResolvedValue({ count: 0 });

    act(() => useUpdatesSeenStore.getState().markSeen());

    await waitFor(() =>
      expect(unseen).toHaveBeenLastCalledWith(
        useUpdatesSeenStore.getState().lastSeenAt,
      ),
    );
    expect(useUpdatesSeenStore.getState().lastSeenAt).not.toBe(SEEN);
  });
});

describe("live refresh", () => {
  beforeEach(() => {
    handlers.clear();
  });

  it("refreshes every update query when GAIA tells the user something", () => {
    const { client, wrapper } = clientWrapper();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    renderHook(() => useUpdatesLiveRefresh(), { wrapper });

    handlers.get("outbox.message")?.({ kind: "conversation_message" });

    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["updates"] });
  });

  it("stops listening when it unmounts", () => {
    const { wrapper } = clientWrapper();
    const { unmount } = renderHook(() => useUpdatesLiveRefresh(), { wrapper });

    unmount();

    expect(handlers.has("outbox.message")).toBe(false);
  });
});

describe("marking the page seen", () => {
  beforeEach(() => {
    handlers.clear();
    localStorage.clear();
    useUpdatesSeenStore.setState({ lastSeenAt: SEEN });
  });

  it("counts what is told while the page is open as seen", () => {
    const { wrapper } = clientWrapper();
    renderHook(() => useMarkUpdatesSeen(), { wrapper });
    useUpdatesSeenStore.setState({ lastSeenAt: SEEN });

    act(() =>
      handlers.get("outbox.message")?.({ kind: "conversation_message" }),
    );

    expect(useUpdatesSeenStore.getState().lastSeenAt).not.toBe(SEEN);
  });

  it("counts what was told up to the moment the user leaves as seen", () => {
    const { wrapper } = clientWrapper();
    const { unmount } = renderHook(() => useMarkUpdatesSeen(), { wrapper });
    useUpdatesSeenStore.setState({ lastSeenAt: SEEN });

    unmount();

    expect(useUpdatesSeenStore.getState().lastSeenAt).not.toBe(SEEN);
    expect(handlers.has("outbox.message")).toBe(false);
  });
});
