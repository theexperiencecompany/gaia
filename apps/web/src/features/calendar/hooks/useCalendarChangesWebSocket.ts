"use client";

import { type QueryClient, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { wsManager } from "@/lib/websocket/WebSocketManager";

import { calendarKeys } from "../api/queryKeys";

/** The push the server sends after it changed one of the user's calendar events. */
export const CALENDAR_CHANGED_EVENT = "calendar.changed";

/** Re-read every cached event range; a socket (re)connect does too, since a push may have been missed. */
export const invalidateCalendarEvents = (queryClient: QueryClient) => {
  void queryClient.invalidateQueries({ queryKey: calendarKeys.events });
  void queryClient.invalidateQueries({ queryKey: calendarKeys.upcoming });
};

export function useCalendarChangesWebSocket(): void {
  const queryClient = useQueryClient();

  useEffect(() => {
    const refresh = () => invalidateCalendarEvents(queryClient);
    wsManager.on(CALENDAR_CHANGED_EVENT, refresh);
    wsManager.onConnect(refresh);
    return () => {
      wsManager.off(CALENDAR_CHANGED_EVENT, refresh);
      wsManager.offConnect(refresh);
    };
  }, [queryClient]);
}
