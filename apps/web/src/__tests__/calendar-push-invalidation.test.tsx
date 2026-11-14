// @vitest-environment jsdom
//
// Calendar events are cached server truth with no client copy: the server's
// calendar.changed push (or a socket reconnect) is what re-reads them. This pins
// that the push marks every cached event range and the upcoming list stale, and
// leaves the calendar list and the selection alone.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { calendarKeys } from "@/features/calendar/api/queryKeys";
import {
  CALENDAR_CHANGED_EVENT,
  useCalendarChangesWebSocket,
} from "@/features/calendar/hooks/useCalendarChangesWebSocket";

type Handler = (msg: unknown) => void;
const handlers = new Map<string, Set<Handler>>();
const connectHandlers = new Set<() => void>();

vi.mock("@/lib/websocket/WebSocketManager", () => ({
  wsManager: {
    on: (event: string, handler: Handler) => {
      const set = handlers.get(event) ?? new Set<Handler>();
      set.add(handler);
      handlers.set(event, set);
    },
    off: (event: string, handler: Handler) => {
      handlers.get(event)?.delete(handler);
    },
    onConnect: (handler: () => void) => connectHandlers.add(handler),
    offConnect: (handler: () => void) => connectHandlers.delete(handler),
  },
}));

const NOVEMBER = calendarKeys.monthEvents(["primary"], "2026-11");
const UPCOMING = [...calendarKeys.upcoming, 10, "2026-11-14", "2026-12-14"];

const seeded = () => {
  const queryClient = new QueryClient();
  queryClient.setQueryData(NOVEMBER, []);
  queryClient.setQueryData(UPCOMING, []);
  queryClient.setQueryData(calendarKeys.calendars, []);
  queryClient.setQueryData(calendarKeys.preferences, ["primary"]);
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  renderHook(() => useCalendarChangesWebSocket(), { wrapper });
  return queryClient;
};

const isStale = (queryClient: QueryClient, key: readonly unknown[]) =>
  queryClient.getQueryState(key)?.isInvalidated;

describe("calendar push", () => {
  beforeEach(() => {
    handlers.clear();
    connectHandlers.clear();
  });

  it("marks the cached events stale and nothing else", async () => {
    const queryClient = seeded();

    await act(async () => {
      for (const handler of handlers.get(CALENDAR_CHANGED_EVENT) ?? []) {
        handler({ type: CALENDAR_CHANGED_EVENT });
      }
    });

    expect(isStale(queryClient, NOVEMBER)).toBe(true);
    expect(isStale(queryClient, UPCOMING)).toBe(true);
    expect(isStale(queryClient, calendarKeys.calendars)).toBe(false);
    expect(isStale(queryClient, calendarKeys.preferences)).toBe(false);
  });

  it("marks the cached events stale on a reconnect, which may have missed pushes", async () => {
    const queryClient = seeded();

    await act(async () => {
      for (const handler of connectHandlers) handler();
    });

    expect(isStale(queryClient, NOVEMBER)).toBe(true);
  });
});
