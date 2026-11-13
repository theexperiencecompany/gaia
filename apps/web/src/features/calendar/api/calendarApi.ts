import type {
  CalendarEventsResponse,
  EventDeleteRequest,
  EventUpdateRequest,
} from "@shared/api/generated";
import { api } from "@/lib/api/typed";
import type {
  CalendarEventsResult,
  CalendarItem,
} from "@/types/api/calendarApiTypes";
import {
  asGoogleCalendarEvent,
  asGoogleCalendarEvents,
  type EventCreatePayload,
} from "@/types/features/calendarTypes";

/** The API's event page with the passthrough events narrowed to Google's shape. */
const toEventsResult = (
  page: CalendarEventsResponse,
): CalendarEventsResult => ({
  ...page,
  events: asGoogleCalendarEvents(page.events),
});

export const calendarApi = {
  // Fetch events from multiple calendars with date-based pagination
  // Uses POST to avoid URL length limits with many calendars
  // When fetch_all=true, fetches ALL events in the date range (for calendar page)
  fetchMultipleCalendarEvents: async (
    calendarIds: string[],
    startDate?: string, // YYYY-MM-DD format
    endDate?: string, // YYYY-MM-DD format
    fetchAll = true, // Default to true for calendar page - fetches ALL events
  ): Promise<CalendarEventsResult> => {
    if (!calendarIds.length) {
      return {
        events: [],
        has_more: false,
        calendars_truncated: [],
        selectedCalendars: [],
      };
    }

    const page = await api.post("/api/v1/calendar/events/query", {
      body: {
        selected_calendars: calendarIds,
        start_date: startDate,
        end_date: endDate,
        fetch_all: fetchAll,
      },
      silent: true,
    });
    return toEventsResult(page);
  },

  // Fetch available calendars
  fetchCalendars: async (): Promise<CalendarItem[]> => {
    const response = await api.get("/api/v1/calendar/list", { silent: true });

    // Map Google Calendar API response to our Calendar type
    return response.items.map((item) => ({
      id: item.id,
      name: item.summary ?? "",
      summary: item.summary ?? "",
      backgroundColor: item.backgroundColor ?? undefined,
      primary: item.primary ?? false,
    }));
  },

  // Fetch calendar preferences
  fetchCalendarPreferences: async (): Promise<string[]> => {
    try {
      const data = await api.get("/api/v1/calendar/preferences", {
        silent: true,
      });
      return data.selectedCalendars;
    } catch (error) {
      console.error("Error fetching calendar preferences:", error);
      return [];
    }
  },

  // Update calendar preferences
  updateCalendarPreferences: async (calendarIds: string[]): Promise<void> => {
    await api.put("/api/v1/calendar/preferences", {
      body: { selected_calendars: calendarIds },
      silent: true,
    });
  },

  // Create event without specifying calendar ID (uses default calendar)
  createEventDefault: async (event: EventCreatePayload) =>
    asGoogleCalendarEvent(
      await api.post("/api/v1/calendar/event", {
        body: event,
        errorMessage: "Failed to add event",
      }),
    ),

  // Delete event via agent tool (unified endpoint)
  deleteEventByAgent: (
    deletePayload: EventDeleteRequest,
    options?: { silent?: boolean },
  ) =>
    api.delete("/api/v1/calendar/event", {
      body: deletePayload,
      successMessage: options?.silent
        ? undefined
        : "Event deleted successfully!",
      errorMessage: "Failed to delete event",
    }),

  // Update event via agent tool (unified endpoint)
  updateEventByAgent: async (updatePayload: EventUpdateRequest) =>
    asGoogleCalendarEvent(
      await api.put("/api/v1/calendar/event", {
        body: updatePayload,
        successMessage: "Event updated successfully!",
        errorMessage: "Failed to update event",
      }),
    ),
};
